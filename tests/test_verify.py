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
    fetch_https,
    refuse_root,
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
        # Not root — never raises
        refuse_root(allow=False)
        refuse_root(allow=True)
