"""Per-forge release-asset resolvers (SPEC Phase D — Round 3 #19).

The registry.json schema gained a per-version ``forge`` block in
v0.4.0 (commit ``08db77e``). This module turns that informational
block into actual URL resolution: given the forge type + owner +
repo + version, return the URL where the release asset lives.

Five forges are first-class:

- ``github``    — ``https://api.github.com/repos/{owner}/{repo}/releases/...``
- ``gitlab``    — ``https://gitlab.com/api/v4/projects/{owner}%2F{repo}/releases/...``
- ``codeberg``  — Gitea-flavoured at ``https://codeberg.org/api/v1``
- ``gitea``     — generic Gitea host (the user provides ``host`` in extras)
- ``bitbucket`` — ``https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}/downloads``

Each resolver returns a URL string that downstream callers feed
through :func:`get_installer.verify.fetch_https` so the existing
HTTPS-only / allowlist / sha256 enforcement still applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ForgeError(Exception):
    """Raised when a forge metadata block is malformed or unresolvable."""


@dataclass(frozen=True)
class ForgeSpec:
    """Parsed forge metadata. Built from the registry.json ``forge`` block.

    @field type           one of github|gitlab|codeberg|gitea|bitbucket
    @field owner          org / user / workspace name
    @field repo           repository name
    @field release_tag_template  how to compute the tag from a version
                          (default ``"v{version}"``)
    @field asset_pattern  optional glob matching the release asset filename
    @field host           custom hostname (gitea only; defaults per forge)
    """

    type: str
    owner: str
    repo: str
    release_tag_template: str = "v{version}"
    asset_pattern: str | None = None
    host: str | None = None


SUPPORTED_FORGES: tuple[str, ...] = ("github", "gitlab", "codeberg", "gitea", "bitbucket")


def parse_forge_spec(block: dict[str, Any]) -> ForgeSpec:
    """Build a ForgeSpec from the registry.json ``forge`` dict."""
    forge_type = str(block.get("type", ""))
    if forge_type not in SUPPORTED_FORGES:
        raise ForgeError(
            f"unsupported forge type {forge_type!r}; "
            f"expected one of {SUPPORTED_FORGES}"
        )
    owner = str(block.get("owner", ""))
    repo = str(block.get("repo", ""))
    if not owner or not repo:
        raise ForgeError(
            f"forge {forge_type}: missing owner/repo "
            f"(got owner={owner!r}, repo={repo!r})"
        )
    return ForgeSpec(
        type=forge_type,
        owner=owner,
        repo=repo,
        release_tag_template=str(block.get("release_tag_template", "v{version}")),
        asset_pattern=block.get("asset_pattern"),
        host=block.get("host"),
    )


def release_tag(spec: ForgeSpec, version: str) -> str:
    """Compute the release tag for a given version + template."""
    return spec.release_tag_template.replace("{version}", version)


# --- per-forge resolvers ---------------------------------------------------


def github_release_url(spec: ForgeSpec, version: str, asset: str) -> str:
    """Direct asset URL for a GitHub release."""
    tag = release_tag(spec, version)
    return (
        f"https://github.com/{spec.owner}/{spec.repo}"
        f"/releases/download/{tag}/{asset}"
    )


def github_release_api_url(spec: ForgeSpec, version: str) -> str:
    """API URL for a GitHub release's metadata (asset list, SHA, etc.)."""
    tag = release_tag(spec, version)
    return (
        f"https://api.github.com/repos/{spec.owner}/{spec.repo}"
        f"/releases/tags/{tag}"
    )


def gitlab_release_api_url(spec: ForgeSpec, version: str) -> str:
    """GitLab Releases API URL. ``owner/repo`` is URL-encoded."""
    tag = release_tag(spec, version)
    project = f"{spec.owner}%2F{spec.repo}"
    return f"https://gitlab.com/api/v4/projects/{project}/releases/{tag}"


def codeberg_release_api_url(spec: ForgeSpec, version: str) -> str:
    """Codeberg uses Gitea's API at codeberg.org."""
    tag = release_tag(spec, version)
    return (
        f"https://codeberg.org/api/v1/repos/{spec.owner}/{spec.repo}"
        f"/releases/tags/{tag}"
    )


def gitea_release_api_url(spec: ForgeSpec, version: str) -> str:
    """Generic Gitea host. ``host`` extras key required."""
    if not spec.host:
        raise ForgeError(
            "gitea forge requires a 'host' field "
            "(e.g., 'host: gitea.my-org.com')"
        )
    tag = release_tag(spec, version)
    return (
        f"https://{spec.host}/api/v1/repos/{spec.owner}/{spec.repo}"
        f"/releases/tags/{tag}"
    )


def bitbucket_download_url(spec: ForgeSpec, version: str, asset: str) -> str:
    """Bitbucket downloads area — assets live under /downloads/, not releases."""
    return (
        f"https://bitbucket.org/{spec.owner}/{spec.repo}"
        f"/downloads/{asset}"
    )


# --- unified entry point ---------------------------------------------------


def resolve_release_metadata_url(spec: ForgeSpec, version: str) -> str:
    """Return the URL that lists release metadata (assets + checksums).

    The caller fetches this JSON (via verify.fetch_https) and finds
    the asset matching ``spec.asset_pattern`` if set, else the sdist.

    @raises ForgeError on bitbucket (no metadata API; assets are
        downloaded by direct URL via :func:`bitbucket_download_url`).
    """
    if spec.type == "github":
        return github_release_api_url(spec, version)
    if spec.type == "gitlab":
        return gitlab_release_api_url(spec, version)
    if spec.type == "codeberg":
        return codeberg_release_api_url(spec, version)
    if spec.type == "gitea":
        return gitea_release_api_url(spec, version)
    if spec.type == "bitbucket":
        raise ForgeError(
            "bitbucket has no release-metadata API; "
            "use bitbucket_download_url() with an explicit asset name"
        )
    raise ForgeError(f"no resolver for forge type {spec.type!r}")


def resolve_asset_url(spec: ForgeSpec, version: str, asset: str) -> str:
    """Return the direct download URL for a named release asset."""
    if spec.type == "github":
        return github_release_url(spec, version, asset)
    if spec.type == "bitbucket":
        return bitbucket_download_url(spec, version, asset)
    if spec.type in {"gitlab", "codeberg", "gitea"}:
        # These forges return asset URLs via the release-metadata API;
        # the caller resolves them from there. We surface a clear
        # exception so callers don't accidentally guess.
        raise ForgeError(
            f"{spec.type}: use resolve_release_metadata_url() to fetch the "
            "release JSON and read the asset URL from its 'assets' list"
        )
    raise ForgeError(f"no resolver for forge type {spec.type!r}")
