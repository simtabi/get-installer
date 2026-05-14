"""Tests for ``Registry.from_url`` — remote registry source (Phase C)."""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
import time
from pathlib import Path

import pytest

from get_installer import ConfigError, Registry
from get_installer.verify import SecurityError

BASE_REGISTRY = {
    "schema_version": 2,
    "registry_updated": "2026-05-14",
    "products": {
        "demo": {
            "name": "demo",
            "summary": "demo",
            "default_version": "1.0.0",
            "versions": {
                "1.0.0": {
                    "status": "current",
                    "package": "demo-pkg",
                    "min_python": "3.10",
                    "install_method": "pipx",
                },
            },
        }
    },
}


@pytest.fixture
def http_server(tmp_path_factory: pytest.TempPathFactory):
    """Local plain-HTTP server returning JSON. We override the scheme guard
    in tests by monkeypatching ``fetch_https``."""
    served = tmp_path_factory.mktemp("served")
    (served / "registry.json").write_text(json.dumps(BASE_REGISTRY), encoding="utf-8")
    (served / "bad.json").write_text("{not json", encoding="utf-8")

    captured_headers: list[dict[str, str]] = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(served), **kw)

        def do_GET(self):
            captured_headers.append(dict(self.headers))
            return super().do_GET()

        def log_message(self, *_a, **_kw):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], served, captured_headers
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def http_fetch(monkeypatch: pytest.MonkeyPatch):
    """Replace ``verify.fetch_https`` with a plain-HTTP version so the
    local server fixture works. We still test scheme + allowlist enforcement
    via direct calls to ``fetch_https`` elsewhere."""
    import urllib.request

    from get_installer import verify

    def fake_fetch(
        url, dest, *, max_bytes=10 * 1024 * 1024, timeout=30.0,
        max_retries=0, retry_backoff_seconds=(1.0,),
        deadline_seconds=None, allowed_origins=(),
        file_mode=0o600, extra_headers=None,
    ):
        # Honour the allowlist check even in the fake — that's part of what
        # Phase C plumbing needs to verify.
        if allowed_origins and not any(
            url.startswith(p) for p in allowed_origins
        ):
            raise SecurityError(f"URL not in allowed_origins: {url}")
        headers = {"User-Agent": "get-installer-test/1.0"}
        if extra_headers:
            for k, v in extra_headers.items():
                if "\r" in v or "\n" in v:
                    raise SecurityError(f"refusing header CRLF for {k!r}")
                headers[k] = v
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SecurityError(f"exceeds {max_bytes}")
        dest.write_bytes(data)
        return len(data)

    monkeypatch.setattr(verify, "fetch_https", fake_fetch)
    # Re-route the import inside config.py too
    from get_installer import config as _cfg_mod
    monkeypatch.setattr(_cfg_mod, "verify", verify)


# --- happy path -----------------------------------------------------------


def test_from_url_loads_registry(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, _ = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    reg = Registry.from_url(url, cache_dir=tmp_path / "cache")
    assert "demo" in reg.products


def test_from_url_sends_auth_header(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, headers_log = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    Registry.from_url(url, auth_token="my-secret", cache_dir=tmp_path / "cache")
    assert headers_log
    assert headers_log[-1].get("Authorization") == "Bearer my-secret"


def test_from_url_refuses_header_injection(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, _ = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    with pytest.raises(ConfigError, match="header"):
        Registry.from_url(
            url, auth_token="x\r\nX-Injected: y",
            cache_dir=tmp_path / "cache",
        )


# --- caching --------------------------------------------------------------


def test_from_url_writes_cache(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, _ = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    cache = tmp_path / "cache"
    Registry.from_url(url, cache_dir=cache)
    assert any(cache.glob("registry-*.json"))


def test_from_url_uses_cache_when_fresh(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, headers_log = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    cache = tmp_path / "cache"
    Registry.from_url(url, cache_dir=cache, cache_max_age_seconds=60)
    first_count = len(headers_log)
    # Second call within TTL — should NOT hit the server
    Registry.from_url(url, cache_dir=cache, cache_max_age_seconds=60)
    assert len(headers_log) == first_count, "second call should have hit cache"


def test_from_url_bypasses_cache_when_stale(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, headers_log = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    cache = tmp_path / "cache"
    Registry.from_url(url, cache_dir=cache, cache_max_age_seconds=60)
    first_count = len(headers_log)
    # Force "stale" by setting mtime in the past
    for p in cache.glob("registry-*.json"):
        old = time.time() - 3600
        import os
        os.utime(p, (old, old))
    Registry.from_url(url, cache_dir=cache, cache_max_age_seconds=60)
    assert len(headers_log) == first_count + 1


def test_from_url_refresh_bypasses_cache(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, headers_log = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    cache = tmp_path / "cache"
    Registry.from_url(url, cache_dir=cache, cache_max_age_seconds=60)
    first_count = len(headers_log)
    Registry.from_url(url, cache_dir=cache, cache_max_age_seconds=0)
    assert len(headers_log) == first_count + 1


# --- fallbacks ------------------------------------------------------------


def test_from_url_fallback_on_fetch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No fake fetch — real one. URL won't resolve.
    fallback = tmp_path / "registry.json"
    fallback.write_text(json.dumps(BASE_REGISTRY))
    reg = Registry.from_url(
        "https://there.is.no.host.invalid/registry.json",
        fallback_path=fallback,
        cache_dir=tmp_path / "cache",
        timeout=2,
    )
    assert "demo" in reg.products


def test_from_url_raises_when_no_fallback_and_fetch_fails(
    tmp_path: Path
) -> None:
    with pytest.raises(ConfigError):
        Registry.from_url(
            "https://there.is.no.host.invalid/registry.json",
            cache_dir=tmp_path / "cache",
            timeout=2,
        )


# --- malformed responses --------------------------------------------------


def test_from_url_invalid_json(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, _ = http_server
    url = f"http://127.0.0.1:{port}/bad.json"
    with pytest.raises(ConfigError, match="invalid JSON"):
        Registry.from_url(url, cache_dir=tmp_path / "cache")


# --- allowlist enforcement -----------------------------------------------


def test_from_url_respects_allowed_origins(
    tmp_path: Path, http_server, http_fetch
) -> None:
    port, _, _ = http_server
    url = f"http://127.0.0.1:{port}/registry.json"
    with pytest.raises(ConfigError, match="allowed_origins"):
        Registry.from_url(
            url,
            cache_dir=tmp_path / "cache",
            allowed_origins=("https://only.this.com/",),
        )
