"""Tests for ``scripts/bundle.py`` — verify the single-file bundle works."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCRIPT = REPO_ROOT / "scripts" / "bundle.py"


@pytest.fixture(scope="module")
def bundled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the bundle once per test module."""
    out = tmp_path_factory.mktemp("bundle") / "installer.py"
    r = subprocess.run(
        [sys.executable, str(BUNDLE_SCRIPT), "--output", str(out), "--check"],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, f"bundle build failed:\n{r.stderr}\n{r.stdout}"
    assert out.is_file()
    return out


def test_bundle_is_compileable(bundled: Path) -> None:
    """py_compile must accept the bundled file (already validated by --check)."""
    assert bundled.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")


def test_bundle_size_under_cap(bundled: Path) -> None:
    """Bundle stays under the 200 KB soft cap declared in SPEC."""
    assert bundled.stat().st_size < 200 * 1024


def test_bundle_sha256_sidecar(bundled: Path) -> None:
    """A sidecar ``.sha256`` file with the digest is produced."""
    sidecar = bundled.with_suffix(bundled.suffix + ".sha256")
    assert sidecar.is_file()
    expected = hashlib.sha256(bundled.read_bytes()).hexdigest()
    assert sidecar.read_text(encoding="utf-8").strip() == expected


def test_bundle_reproducible(tmp_path: Path) -> None:
    """Building twice yields byte-identical output.

    Reproducibility is a SPEC requirement (Phase H). The build timestamp
    lives in a sidecar (``installer.py.buildinfo.json``), not in the bundle
    body, so the bundle's sha256 is stable across builds of the same
    source.
    """
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    subprocess.run(
        [sys.executable, str(BUNDLE_SCRIPT), "--output", str(a)],
        capture_output=True, check=True,
    )
    subprocess.run(
        [sys.executable, str(BUNDLE_SCRIPT), "--output", str(b)],
        capture_output=True, check=True,
    )
    assert a.read_bytes() == b.read_bytes(), \
        "bundle is not byte-reproducible — check that no timestamp leaked into the body"
    # The buildinfo sidecar IS allowed to differ (it carries the timestamp)
    assert a.with_suffix(a.suffix + ".buildinfo.json").is_file()
    assert b.with_suffix(b.suffix + ".buildinfo.json").is_file()


def test_bundled_cli_lists_products(bundled: Path) -> None:
    """``python installer.py --list`` works equivalently to the package CLI."""
    r = subprocess.run(
        [sys.executable, str(bundled), "--list",
         "--registry", str(REPO_ROOT / "registry.json")],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "claude-configurator" in r.stdout


def test_bundled_cli_dry_run(bundled: Path) -> None:
    """A dry-run via the bundled file completes the full plan."""
    r = subprocess.run(
        [sys.executable, str(bundled),
         "--registry", str(REPO_ROOT / "registry.json"),
         "--product", "claude-configurator",
         "--dry-run", "--yes"],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "dry-run complete" in r.stdout


def test_bundle_is_importable_as_module(bundled: Path) -> None:
    """Loading the bundle via importlib gives a module with the expected surface.

    Dataclasses in the bundle reference ``cls.__module__`` so we must
    register the module in ``sys.modules`` before exec.
    """
    spec = importlib.util.spec_from_file_location("bundled_installer", bundled)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bundled_installer"] = mod
    try:
        spec.loader.exec_module(mod)
        for name in ("Installer", "Registry", "Journal", "UI", "InstallReport"):
            assert hasattr(mod, name), f"bundle missing top-level name: {name}"
    finally:
        sys.modules.pop("bundled_installer", None)
