from __future__ import annotations

import hashlib
import http.server
import os
import socketserver
import threading
from pathlib import Path

import pytest

from get_installer.verify import (
    SecurityError,
    check_signed_url,
    fetch_https,
    refuse_root,
    require_auth_token,
    resolve_auth_token,
    sha256_of,
    verify_sha256,
)


@pytest.fixture
def http_server(tmp_path: Path):
    """Local HTTP server. We use it via http:// (allow_http=True style)
    because TLS testing is out of scope; the security guards are unit-tested
    with separate negative cases that don't need the network."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(tmp_path), **kw)

        def log_message(self, *_a, **_kw):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], tmp_path
    finally:
        server.shutdown()
        server.server_close()


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    p = tmp_path / "x"
    p.write_bytes(b"hello")
    assert sha256_of(p) == hashlib.sha256(b"hello").hexdigest()


def test_verify_sha256_pass(tmp_path: Path) -> None:
    p = tmp_path / "x"
    p.write_bytes(b"data")
    verify_sha256(p, hashlib.sha256(b"data").hexdigest())


def test_verify_sha256_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "x"
    p.write_bytes(b"data")
    with pytest.raises(SecurityError, match="sha256 mismatch"):
        verify_sha256(p, "0" * 64)


def test_fetch_refuses_http_in_strict_mode(tmp_path: Path) -> None:
    with pytest.raises(SecurityError, match="non-https"):
        fetch_https("http://example.com/x", tmp_path / "out")


def test_fetch_refuses_ftp(tmp_path: Path) -> None:
    with pytest.raises(SecurityError, match="non-https"):
        fetch_https("ftp://example.com/x", tmp_path / "out")


def test_refuse_root_blocks_unless_allowed() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        with pytest.raises(SecurityError):
            refuse_root(allow=False)
        refuse_root(allow=True)
    else:
        # Not root: never raises
        refuse_root(allow=False)
        refuse_root(allow=True)


# --- Phase L: signed-URL expiry validator -------------------------------


def _signed(exp: int, sig: str = "abc123") -> str:
    return f"https://example.com/file.tar.gz?sig={sig}&exp={exp}"


def test_check_signed_url_passes_when_unexpired() -> None:
    check_signed_url(_signed(exp=2000), now=1000)


def test_check_signed_url_rejects_missing_sig() -> None:
    with pytest.raises(SecurityError, match="missing 'sig'"):
        check_signed_url("https://example.com/file.tar.gz?exp=2000", now=1000)


def test_check_signed_url_rejects_missing_expires() -> None:
    with pytest.raises(SecurityError, match="missing 'exp'"):
        check_signed_url("https://example.com/file.tar.gz?sig=abc", now=1000)


def test_check_signed_url_rejects_non_numeric_expires() -> None:
    with pytest.raises(SecurityError, match="not an integer"):
        check_signed_url(
            "https://example.com/file.tar.gz?sig=abc&exp=tomorrow", now=1000
        )


def test_check_signed_url_rejects_expired_past_skew() -> None:
    # exp=1000, max_skew=60, now=1200 -> expired by 140s
    with pytest.raises(SecurityError, match="expired"):
        check_signed_url(_signed(exp=1000), now=1200, max_skew_seconds=60)


def test_check_signed_url_tolerates_skew() -> None:
    # exp=1000, max_skew=60, now=1050 -> within skew tolerance
    check_signed_url(_signed(exp=1000), now=1050, max_skew_seconds=60)


def test_check_signed_url_honors_custom_param_names() -> None:
    url = "https://example.com/file.tar.gz?signature=xyz&expires_at=2000"
    check_signed_url(
        url,
        query_param="signature",
        expires_param="expires_at",
        now=1000,
    )


# --- Phase L: token resolution + require_auth_token ---------------------


def test_resolve_auth_token_prefers_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GET_INSTALLER_TOKEN", "from-env")
    monkeypatch.setenv("PROD_TOKEN", "from-prod-env")
    assert (
        resolve_auth_token("from-cli", product_env_var="PROD_TOKEN")
        == "from-cli"
    )


def test_resolve_auth_token_uses_product_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GET_INSTALLER_TOKEN", "from-global")
    monkeypatch.setenv("PROD_TOKEN", "from-prod")
    assert (
        resolve_auth_token(None, product_env_var="PROD_TOKEN") == "from-prod"
    )


def test_resolve_auth_token_falls_back_to_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROD_TOKEN", raising=False)
    monkeypatch.setenv("GET_INSTALLER_TOKEN", "from-global")
    assert (
        resolve_auth_token(None, product_env_var="PROD_TOKEN")
        == "from-global"
    )


def test_resolve_auth_token_returns_none_when_nothing_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GET_INSTALLER_TOKEN", raising=False)
    monkeypatch.delenv("PROD_TOKEN", raising=False)
    assert resolve_auth_token(None, product_env_var="PROD_TOKEN") is None


def test_require_auth_token_returns_present_token() -> None:
    assert (
        require_auth_token(
            "abc", product_name="thing", env_var="THING_TOKEN"
        )
        == "abc"
    )


def test_require_auth_token_raises_with_hint_url() -> None:
    with pytest.raises(SecurityError, match="THING_TOKEN") as exc:
        require_auth_token(
            None,
            product_name="thing",
            env_var="THING_TOKEN",
            hint_url="https://example.com/get-token",
        )
    assert "https://example.com/get-token" in str(exc.value)


def test_require_auth_token_raises_without_hint_url() -> None:
    with pytest.raises(SecurityError, match="THING_TOKEN") as exc:
        require_auth_token(
            None, product_name="thing", env_var="THING_TOKEN"
        )
    # No "Get a token" sentence when no hint URL
    assert "Get a token" not in str(exc.value)
