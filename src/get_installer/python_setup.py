"""Optional user-space Python bootstrap via ``uv python install``.

Triggered when the system Python doesn't meet ``min_python`` AND the
user passed ``--with-python``. Refuses to touch system Python.
"""

from __future__ import annotations

import shutil
import subprocess


class PythonSetupError(Exception):
    pass


def can_bootstrap() -> bool:
    """True if ``uv`` is available (the only path we use for Python install)."""
    return shutil.which("uv") is not None


def install_via_uv(version: str) -> str:
    """Install Python ``<version>`` via ``uv python install`` and return its path."""
    if not can_bootstrap():
        raise PythonSetupError(
            "uv is not installed. Install uv first (https://docs.astral.sh/uv/) "
            "or install Python manually."
        )
    r = subprocess.run(
        ["uv", "python", "install", version],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        raise PythonSetupError(
            f"uv python install {version} failed: {r.stderr.strip() or r.stdout.strip()}"
        )
    # Resolve the path uv stored it at.
    r2 = subprocess.run(
        ["uv", "python", "find", version],
        capture_output=True, text=True, check=False,
    )
    if r2.returncode != 0:
        raise PythonSetupError(
            f"installed Python {version} but couldn't locate it: {r2.stderr.strip()}"
        )
    return r2.stdout.strip()
