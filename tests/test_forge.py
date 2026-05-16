"""Tests for the forge resolvers (SPEC Phase D)."""

from __future__ import annotations

import pytest

from get_installer.forge import (
    ForgeError,
    ForgeSpec,
    bitbucket_download_url,
    codeberg_release_api_url,
    gitea_release_api_url,
    github_release_api_url,
    github_release_url,
    gitlab_release_api_url,
    parse_forge_spec,
    release_tag,
    resolve_asset_url,
    resolve_release_metadata_url,
)


def _spec(forge_type: str, **extras: object) -> ForgeSpec:
    return parse_forge_spec(
        {"type": forge_type, "owner": "o", "repo": "r", **extras}
    )


# --- parsing -----------------------------------------------------------


def test_parse_minimum_valid_block() -> None:
    spec = _spec("github")
    assert spec.type == "github"
    assert spec.owner == "o"
    assert spec.repo == "r"
    assert spec.release_tag_template == "v{version}"
    assert spec.asset_pattern is None


def test_parse_with_extras() -> None:
    spec = parse_forge_spec(
        {
            "type": "gitlab",
            "owner": "my-group",
            "repo": "my-project",
            "release_tag_template": "release-{version}",
            "asset_pattern": "*.tar.gz",
        }
    )
    assert spec.release_tag_template == "release-{version}"
    assert spec.asset_pattern == "*.tar.gz"


def test_parse_unsupported_type_raises() -> None:
    with pytest.raises(ForgeError, match="unsupported forge type"):
        parse_forge_spec({"type": "sourceforge", "owner": "o", "repo": "r"})


def test_parse_missing_owner_or_repo_raises() -> None:
    with pytest.raises(ForgeError, match="missing owner/repo"):
        parse_forge_spec({"type": "github", "owner": "", "repo": "r"})
    with pytest.raises(ForgeError, match="missing owner/repo"):
        parse_forge_spec({"type": "github", "owner": "o", "repo": ""})


# --- release_tag template ---------------------------------------------


def test_release_tag_default_template() -> None:
    spec = _spec("github")
    assert release_tag(spec, "0.4.0") == "v0.4.0"


def test_release_tag_custom_template() -> None:
    spec = _spec("github", release_tag_template="release/{version}")
    assert release_tag(spec, "0.4.0") == "release/0.4.0"


# --- per-forge URL builders -------------------------------------------


def test_github_release_url() -> None:
    spec = _spec("github")
    assert github_release_url(spec, "0.4.0", "installer.py") == (
        "https://github.com/o/r/releases/download/v0.4.0/installer.py"
    )


def test_github_release_api_url() -> None:
    spec = _spec("github")
    assert github_release_api_url(spec, "0.4.0") == (
        "https://api.github.com/repos/o/r/releases/tags/v0.4.0"
    )


def test_gitlab_release_api_url_urlencodes_owner_repo() -> None:
    spec = _spec("gitlab")
    assert gitlab_release_api_url(spec, "0.4.0") == (
        "https://gitlab.com/api/v4/projects/o%2Fr/releases/v0.4.0"
    )


def test_codeberg_release_api_url() -> None:
    spec = _spec("codeberg")
    assert codeberg_release_api_url(spec, "0.4.0") == (
        "https://codeberg.org/api/v1/repos/o/r/releases/tags/v0.4.0"
    )


def test_gitea_release_api_url_with_host() -> None:
    spec = _spec("gitea", host="gitea.example.com")
    assert gitea_release_api_url(spec, "0.4.0") == (
        "https://gitea.example.com/api/v1/repos/o/r/releases/tags/v0.4.0"
    )


def test_gitea_requires_host() -> None:
    spec = _spec("gitea")
    with pytest.raises(ForgeError, match="requires a 'host' field"):
        gitea_release_api_url(spec, "0.4.0")


def test_bitbucket_download_url() -> None:
    spec = _spec("bitbucket")
    assert bitbucket_download_url(spec, "0.4.0", "installer.py") == (
        "https://bitbucket.org/o/r/downloads/installer.py"
    )


# --- unified resolvers ------------------------------------------------


def test_resolve_release_metadata_url_dispatches() -> None:
    assert "github" in resolve_release_metadata_url(_spec("github"), "0.4.0")
    assert "gitlab" in resolve_release_metadata_url(_spec("gitlab"), "0.4.0")
    assert "codeberg" in resolve_release_metadata_url(_spec("codeberg"), "0.4.0")
    assert "example" in resolve_release_metadata_url(
        _spec("gitea", host="gitea.example.com"), "0.4.0"
    )


def test_resolve_release_metadata_url_bitbucket_raises() -> None:
    with pytest.raises(ForgeError, match="bitbucket has no release-metadata API"):
        resolve_release_metadata_url(_spec("bitbucket"), "0.4.0")


def test_resolve_asset_url_github() -> None:
    url = resolve_asset_url(_spec("github"), "0.4.0", "installer.py")
    assert url == "https://github.com/o/r/releases/download/v0.4.0/installer.py"


def test_resolve_asset_url_bitbucket() -> None:
    url = resolve_asset_url(_spec("bitbucket"), "0.4.0", "installer.py")
    assert url == "https://bitbucket.org/o/r/downloads/installer.py"


def test_resolve_asset_url_gitlab_directs_to_metadata_api() -> None:
    """gitlab/codeberg/gitea: must use the metadata API + read assets[] from JSON."""
    with pytest.raises(ForgeError, match="use resolve_release_metadata_url"):
        resolve_asset_url(_spec("gitlab"), "0.4.0", "installer.py")
