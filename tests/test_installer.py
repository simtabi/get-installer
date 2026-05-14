from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from get_installer import UI, InstallConfig, Installer, Registry


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    data = {
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
                        "required_commands": [],
                        "post_install": [
                            {"argv": ["echo", "always"]},
                            {"argv": ["echo", "gated"], "if": "go=yes"},
                        ],
                        "prompts": [
                            {"key": "go", "type": "yes_no", "question": "?", "default": True}
                        ],
                    }
                },
            }
        },
    }
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(data))
    return Registry.load(p)


@pytest.fixture
def silent_ui() -> UI:
    """A UI that suppresses output but answers prompts with defaults."""
    import io
    return UI(assume_yes=True, quiet=True, no_color=True, stream=io.StringIO())


def test_dry_run_makes_no_changes(registry: Registry, silent_ui: UI) -> None:
    cfg = registry.resolve("demo")
    inst = Installer(cfg, ui=silent_ui, dry_run=True)
    report = inst.run()
    assert report.success
    assert not report.package_installed
    assert not report.rolled_back


def test_validate_phase_rejects_old_python(
    registry: Registry, silent_ui: UI
) -> None:
    data = registry.products["demo"]["versions"]["1.0.0"].copy()
    data["min_python"] = "99.0"
    raw = {
        "schema_version": 2,
        "registry_updated": "2026-05-14",
        "products": {
            "demo": {
                "name": "demo", "summary": "x", "default_version": "1.0.0",
                "versions": {"1.0.0": data},
            }
        },
    }
    reg = Registry.from_dict(raw)
    cfg = reg.resolve("demo")
    inst = Installer(cfg, ui=silent_ui, dry_run=False)
    report = inst.run()
    assert not report.success
    assert "Python" in (report.error or "")


def test_post_install_gate_skips_when_answer_mismatches(
    registry: Registry, silent_ui: UI
) -> None:
    cfg = registry.resolve("demo")
    inst = Installer(cfg, ui=silent_ui)
    inst._prompt_answers["go"] = "no"
    # Run only the post-install phase directly to isolate behaviour
    ran = inst._phase_post_install()
    assert ran == 1  # only the unguarded "echo always"


def test_post_install_gate_runs_when_answer_matches(
    registry: Registry, silent_ui: UI
) -> None:
    cfg = registry.resolve("demo")
    inst = Installer(cfg, ui=silent_ui)
    inst._prompt_answers["go"] = "yes"
    ran = inst._phase_post_install()
    assert ran == 2


def test_root_refused_without_flag(registry: Registry, silent_ui: UI) -> None:
    cfg = registry.resolve("demo")
    inst = Installer(cfg, ui=silent_ui, allow_root=False)
    with patch("os.geteuid", return_value=0, create=True):
        report = inst.run()
        # On systems without os.geteuid (Windows), the check is skipped.
        # On Unix, the call should fail with security error.
        if hasattr(sys, "real_prefix") or hasattr(__import__("os"), "geteuid"):
            assert not report.success
            assert "root" in (report.error or "").lower()


def test_unknown_install_method_fails(
    registry: Registry, silent_ui: UI, tmp_path: Path
) -> None:
    # Force a bad install_method by constructing an InstallConfig directly
    cfg = registry.resolve("demo")
    bad = InstallConfig(
        product=cfg.product, version=cfg.version, status=cfg.status,
        status_reason=cfg.status_reason, released=cfg.released,
        package=cfg.package, package_version=cfg.package_version,
        min_python=cfg.min_python, install_method="bogus",
        required_commands=cfg.required_commands,
        optional_commands=cfg.optional_commands,
        post_install=cfg.post_install, content_repo=cfg.content_repo,
        prompts=cfg.prompts, next_steps=cfg.next_steps,
        package_sha256=cfg.package_sha256,
        supported_platforms=cfg.supported_platforms,
        homepage=cfg.homepage, summary=cfg.summary,
    )
    inst = Installer(bad, ui=silent_ui)
    report = inst.run()
    assert not report.success
