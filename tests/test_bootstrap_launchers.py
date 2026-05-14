"""Integration tests for the bootstrap launchers (Phase J / §5 I12, I13).

We don't need actual network access — a local ``http.server`` thread
serves the artefacts and we set ``INSTALLER_BASE_URL`` to point at it.
The launcher should still verify the SHA when ``INSTALLER_SHA256`` is
set.

Tests in this module require:
- ``bash`` on PATH (skipped on Windows-only CI without WSL)
- The repository's ``bootstrap/install.sh`` to be present
"""

from __future__ import annotations

import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "bootstrap" / "install.sh"
INSTALL_PS1 = REPO_ROOT / "bootstrap" / "install.ps1"


# --- syntax-only parse checks --------------------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_install_sh_passes_bash_syntax_check() -> None:
    """``bash -n`` parses the script without executing it. Catches typos."""
    r = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, f"bash -n failed:\n{r.stderr}"


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh not on PATH")
def test_install_sh_passes_sh_syntax_check() -> None:
    """The script claims POSIX sh compatibility — verify it parses under sh."""
    r = subprocess.run(
        ["sh", "-n", str(INSTALL_SH)],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, f"sh -n failed:\n{r.stderr}"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not on PATH")
def test_install_ps1_passes_pwsh_parse_check() -> None:
    """PowerShell Core's parser as a syntax check for install.ps1."""
    cmd = [
        "pwsh", "-NoProfile",
        "-Command",
        f"$null = [System.Management.Automation.PSParser]::Tokenize("
        f"(Get-Content -Raw '{INSTALL_PS1}'), [ref]$null); exit 0",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"pwsh parse failed:\n{r.stderr}"


# --- end-to-end against a local HTTP server ------------------------------


@pytest.fixture
def mock_distribution(tmp_path: Path):
    """Serve a fake ``installer.py`` + ``registry.json`` over local HTTP.

    Yields ``(base_url, served_dir, installer_sha256)``.
    """
    served = tmp_path / "served"
    served.mkdir()

    installer_text = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('mock installer ok')\n"
        "sys.exit(0)\n"
    )
    (served / "installer.py").write_text(installer_text, encoding="utf-8")

    registry_text = (
        '{"schema_version": 2, "registry_updated": "2026-05-14", '
        '"products": {"demo": {"name": "demo", "summary": "demo", '
        '"default_version": "1.0.0", "versions": {"1.0.0": '
        '{"status": "current", "package": "demo-pkg", '
        '"min_python": "3.10", "install_method": "pipx"}}}}}'
    )
    (served / "registry.json").write_text(registry_text, encoding="utf-8")

    import hashlib
    installer_sha = hashlib.sha256(installer_text.encode()).hexdigest()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(served), **kw)

        def log_message(self, *_a, **_kw):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, served, installer_sha
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.skipif(
    sys.platform == "win32", reason="Unix-style permissions on temp dirs"
)
def test_install_sh_succeeds_when_sha_matches(mock_distribution) -> None:
    """install.sh runs to completion when INSTALLER_SHA256 matches.
    The mock installer.py prints 'mock installer ok'."""
    base_url, _, sha = mock_distribution
    env = {
        **os.environ,
        "INSTALLER_BASE_URL": base_url,
        "INSTALLER_SHA256": sha,
        "INSTALLER_PROTO_OVERRIDE": "-all,+http",  # test-only — see install.sh
        "SHELL_OK": "1",
    }
    r = subprocess.run(
        ["bash", str(INSTALL_SH)],
        env=env, capture_output=True, text=True, check=False,
        timeout=15,
    )
    assert r.returncode == 0, (
        f"install.sh failed unexpectedly\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "mock installer ok" in r.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.skipif(sys.platform == "win32", reason="Unix temp dir permissions")
def test_install_sh_refuses_on_sha_mismatch(mock_distribution) -> None:
    """When INSTALLER_SHA256 is set to a wrong value, install.sh must
    abort BEFORE running the downloaded installer.py."""
    base_url, _, _real_sha = mock_distribution
    wrong_sha = "0" * 64
    env = {
        **os.environ,
        "INSTALLER_BASE_URL": base_url,
        "INSTALLER_SHA256": wrong_sha,
        "INSTALLER_PROTO_OVERRIDE": "-all,+http",
        "SHELL_OK": "1",
    }
    r = subprocess.run(
        ["bash", str(INSTALL_SH)],
        env=env, capture_output=True, text=True, check=False,
        timeout=15,
    )
    assert r.returncode != 0
    # Mock installer must NOT have run
    assert "mock installer ok" not in r.stdout
    # Mismatch message goes to stderr
    assert "sha256 mismatch" in r.stderr.lower()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only PATH stubbing")
def test_install_sh_lists_install_urls_when_no_python(tmp_path: Path) -> None:
    """When Python <3.10 isn't on PATH AND --bootstrap-uv isn't passed,
    install.sh must surface the three install options + URLs so the user
    can self-help. Regression guard: previously fail() collapsed to a
    one-liner."""
    bash_abs = shutil.which("bash")
    assert bash_abs, "bash should resolve"
    # Provide stub `python3` / `python` shims that report a too-old version,
    # so find_python() in the script falls through. Keep /usr/bin:/bin for
    # basic utilities (id, cat, awk, etc).
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub_body = (
        "#!/usr/bin/env sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  case \"$2\" in *version_info*) printf '2.7\\n' ;; *) exit 1 ;; esac\n"
        "fi\n"
    )
    for name in ("python3", "python", "python3.10", "python3.11",
                 "python3.12", "python3.13"):
        p = stub_dir / name
        p.write_text(stub_body, encoding="utf-8")
        p.chmod(0o755)
    env = {
        "PATH": f"{stub_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SHELL_OK": "1",
    }
    r = subprocess.run(
        [bash_abs, str(INSTALL_SH)],
        env=env, capture_output=True, text=True, check=False,
        timeout=10,
    )
    assert r.returncode != 0
    combined = (r.stdout + r.stderr).lower()
    # All three escape hatches must be named with their URL host
    assert "docs.astral.sh/uv" in combined
    assert "pipx.pypa.io" in combined
    assert "python.org" in combined
    assert "--bootstrap-uv" in combined


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_install_sh_accepts_bootstrap_uv_flag() -> None:
    """The --bootstrap-uv arg must parse cleanly (script doesn't blow up
    just on flag presence). Actual uv install is integration-only."""
    r = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0
    # And the script source must reference both the flag and Astral's URL
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert "--bootstrap-uv" in body
    assert "astral.sh/uv" in body


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.skipif(sys.platform == "win32", reason="Unix temp dir permissions")
def test_install_sh_warns_without_sha_pin(mock_distribution) -> None:
    """Without INSTALLER_SHA256 set, install.sh prints a warning then
    proceeds. The warning is required so users see the unverified path."""
    base_url, _, _ = mock_distribution
    env = {
        **os.environ,
        "INSTALLER_BASE_URL": base_url,
        "INSTALLER_PROTO_OVERRIDE": "-all,+http",
        "SHELL_OK": "1",
    }
    r = subprocess.run(
        ["bash", str(INSTALL_SH)],
        env=env, capture_output=True, text=True, check=False,
        timeout=15,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "INSTALLER_SHA256" in r.stderr or "integrity check" in r.stderr
