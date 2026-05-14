from __future__ import annotations

import json
from pathlib import Path

import pytest

from get_installer import (
    ConfigError,
    InstallConfig,
    PostInstallStep,
    Prompt,
    Registry,
    ResolutionError,
)


@pytest.fixture
def base_registry() -> dict:
    return {
        "schema_version": 2,
        "registry_updated": "2026-05-14",
        "products": {
            "demo": {
                "name": "demo",
                "summary": "demo product",
                "default_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "status": "current",
                        "package": "demo-pkg",
                        "min_python": "3.10",
                        "install_method": "auto",
                    },
                    "0.9.0": {
                        "status": "deprecated",
                        "status_reason": "old; upgrade",
                        "package": "demo-pkg",
                        "min_python": "3.10",
                        "install_method": "pipx",
                    },
                    "0.1.0": {
                        "status": "yanked",
                        "status_reason": "had a critical bug",
                        "package": "demo-pkg",
                        "min_python": "3.10",
                        "install_method": "pipx",
                    },
                },
            }
        },
    }


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(data))
    return p


# --- schema validation ----------------------------------------------------


def test_load_valid_registry(tmp_path: Path, base_registry: dict) -> None:
    p = _write(tmp_path, base_registry)
    reg = Registry.load(p)
    assert reg.schema_version == 2
    assert reg.registry_updated == "2026-05-14"
    assert "demo" in reg.products


def test_load_rejects_wrong_schema(tmp_path: Path, base_registry: dict) -> None:
    base_registry["schema_version"] = 99
    p = _write(tmp_path, base_registry)
    with pytest.raises(ConfigError, match="schema_version"):
        Registry.load(p)


def test_load_rejects_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(ConfigError, match="invalid JSON"):
        Registry.load(p)


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        Registry.load(tmp_path / "nope.json")


def test_load_rejects_bad_date(tmp_path: Path, base_registry: dict) -> None:
    base_registry["registry_updated"] = "not-a-date"
    with pytest.raises(ConfigError, match="registry_updated"):
        Registry.load(_write(tmp_path, base_registry))


# --- resolution -----------------------------------------------------------


def test_resolve_default_version(tmp_path: Path, base_registry: dict) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    cfg = reg.resolve("demo")
    assert isinstance(cfg, InstallConfig)
    assert cfg.product == "demo"
    assert cfg.version == "1.0.0"
    assert cfg.is_current


def test_resolve_unknown_product_lists_options(
    tmp_path: Path, base_registry: dict
) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ResolutionError, match=r"unknown product 'foo'.*demo"):
        reg.resolve("foo")


def test_resolve_unknown_version_lists_options(
    tmp_path: Path, base_registry: dict
) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ResolutionError, match=r"unknown version '9.9.9'.*1.0.0"):
        reg.resolve("demo", "9.9.9")


def test_resolve_yanked_always_refuses(
    tmp_path: Path, base_registry: dict
) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ResolutionError, match="yanked"):
        reg.resolve("demo", "0.1.0", allow_deprecated=True, allow_unsupported=True)


def test_resolve_deprecated_with_default_flag(
    tmp_path: Path, base_registry: dict
) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    cfg = reg.resolve("demo", "0.9.0")  # allow_deprecated=True default
    assert cfg.is_deprecated
    assert cfg.status_reason == "old; upgrade"


def test_resolve_deprecated_refused_with_flag(
    tmp_path: Path, base_registry: dict
) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ResolutionError, match="deprecated"):
        reg.resolve("demo", "0.9.0", allow_deprecated=False)


def test_resolve_platform_filter(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["supported_platforms"] = ["linux"]
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ResolutionError, match="darwin"):
        reg.resolve("demo", platform="darwin")
    assert reg.resolve("demo", platform="linux").product == "demo"


# --- conditional post_install ---------------------------------------------


def test_post_install_legacy_list_form(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [
        ["echo", "hi"]
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    cfg = reg.resolve("demo")
    assert cfg.post_install == (PostInstallStep(argv=("echo", "hi"), if_expr=None),)


def test_post_install_object_form_with_if(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [
        {"argv": ["echo", "hi"], "if": "go=yes"}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    cfg = reg.resolve("demo")
    assert cfg.post_install == (PostInstallStep(argv=("echo", "hi"), if_expr="go=yes"),)


def test_post_install_rejects_bad_if(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [
        {"argv": ["echo"], "if": "missing-equals-sign"}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ConfigError, match="key=value"):
        reg.resolve("demo")


def test_post_install_rejects_empty_argv(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [[]]
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ConfigError, match="non-empty"):
        reg.resolve("demo")


# --- prompts --------------------------------------------------------------


def test_prompt_choice_requires_options(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["versions"]["1.0.0"]["prompts"] = [
        {"key": "x", "type": "choice", "question": "?"}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ConfigError, match="choice type requires"):
        reg.resolve("demo")


def test_prompt_yes_no_minimal(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["products"]["demo"]["versions"]["1.0.0"]["prompts"] = [
        {"key": "x", "type": "yes_no", "question": "?", "default": True}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    cfg = reg.resolve("demo")
    assert cfg.prompts == (Prompt(key="x", type="yes_no", question="?", default=True),)


# --- rate limits & access control -----------------------------------------


def test_default_rate_limits(tmp_path: Path, base_registry: dict) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    assert reg.rate_limits.max_retries == 3
    assert reg.rate_limits.max_total_seconds == 300


def test_custom_rate_limits(tmp_path: Path, base_registry: dict) -> None:
    base_registry["rate_limits"] = {
        "max_retries": 5,
        "max_total_seconds": 60,
    }
    reg = Registry.load(_write(tmp_path, base_registry))
    assert reg.rate_limits.max_retries == 5
    assert reg.rate_limits.max_total_seconds == 60


def test_access_control_https_only(
    tmp_path: Path, base_registry: dict
) -> None:
    base_registry["access_control"] = {
        "allowed_origins": ["http://example.com/"]
    }
    with pytest.raises(ConfigError, match="https://"):
        Registry.load(_write(tmp_path, base_registry))


def test_invalid_log_mode(tmp_path: Path, base_registry: dict) -> None:
    base_registry["access_control"] = {"log_mode": 9999}
    with pytest.raises(ConfigError, match="log_mode"):
        Registry.load(_write(tmp_path, base_registry))


# --- listing --------------------------------------------------------------


def test_list_products_sorts_versions_desc(
    tmp_path: Path, base_registry: dict
) -> None:
    reg = Registry.load(_write(tmp_path, base_registry))
    products = reg.list_products()
    assert len(products) == 1
    assert products[0].available_versions == ("1.0.0", "0.9.0", "0.1.0")


# --- security: argv shell-wrapper rejection ------------------------------


@pytest.mark.parametrize("cmd0", [
    "sh", "bash", "/bin/sh", "/usr/bin/bash",
    "zsh", "dash", "fish",
    "powershell", "pwsh", "cmd.exe",
    "python", "python3", "python3.12",
    "node", "ruby", "perl", "php",
])
def test_post_install_rejects_shell_wrapper_with_dash_c(
    tmp_path: Path, base_registry: dict, cmd0: str
) -> None:
    """``["sh", "-c", "payload"]`` undoes shell=False — refuse it."""
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [
        {"argv": [cmd0, "-c", "echo hi"]}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ConfigError, match="shell-wrapper"):
        reg.resolve("demo")


def test_post_install_allows_shell_wrapper_without_dash_c(
    tmp_path: Path, base_registry: dict
) -> None:
    """``["bash", "/path/to/script.sh"]`` is fine — no ``-c``, no shell interp."""
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [
        {"argv": ["bash", "/path/to/script.sh"]}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    cfg = reg.resolve("demo")
    assert cfg.post_install[0].argv == ("bash", "/path/to/script.sh")


def test_post_install_rejects_control_chars(
    tmp_path: Path, base_registry: dict
) -> None:
    """Control characters in argv hint at injection."""
    base_registry["products"]["demo"]["versions"]["1.0.0"]["post_install"] = [
        {"argv": ["echo", "hi\x00world"]}
    ]
    reg = Registry.load(_write(tmp_path, base_registry))
    with pytest.raises(ConfigError, match="control characters"):
        reg.resolve("demo")
