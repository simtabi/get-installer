"""CLI entry: ``python -m get_installer --registry ... --product NAME [--version V]``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, Registry, ResolutionError, current_platform
from .installer import Installer
from .ui import UI


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="get-installer",
        description="Reusable installer for Simtabi dev tools. Driven by a registry.json.",
    )
    p.add_argument(
        "--registry", "-r",
        type=str, default=None,
        help=(
            "Path or HTTPS URL to registry.json. Defaults to a search of "
            "$GET_INSTALLER_REGISTRY, ./registry.json, and parent dirs."
        ),
    )
    p.add_argument(
        "--auth-token",
        type=str, default=None,
        help=(
            "Bearer token for an HTTPS registry. Falls back to "
            "$GET_INSTALLER_TOKEN. Sent as Authorization: Bearer <token>."
        ),
    )
    p.add_argument(
        "--cache-dir",
        type=Path, default=None,
        help=(
            "Cache fetched registries here. Defaults to "
            "$XDG_CACHE_HOME/get-installer/."
        ),
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached registry and re-fetch.",
    )
    p.add_argument(
        "--product", "-p",
        type=str, default=None,
        help="Which product to install (required unless --list).",
    )
    p.add_argument(
        "--version", "-V",
        type=str, default=None,
        help="Which version (defaults to the product's default_version).",
    )
    p.add_argument(
        "--list", "-l",
        action="store_true",
        help="Print every product + its available versions, then exit.",
    )
    p.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip prompts; assume defaults.",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Print only essential output.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan; touch nothing.",
    )
    p.add_argument(
        "--allow-root",
        action="store_true",
        help="Permit running as root (default: refused).",
    )
    p.add_argument(
        "--allow-deprecated",
        action="store_true", default=True,
        help="Permit installing a deprecated version (default: yes, with a warning).",
    )
    p.add_argument(
        "--no-deprecated",
        dest="allow_deprecated", action="store_false",
        help="Refuse to install a deprecated version.",
    )
    p.add_argument(
        "--allow-unsupported",
        action="store_true",
        help="Permit installing a version marked 'unsupported' (default: refuse).",
    )
    p.add_argument(
        "--with-python",
        action="store_true",
        help="If Python is too old/missing, install via `uv python install`.",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour output.",
    )
    p.add_argument(
        "--version-installer",
        action="version",
        version=f"get-installer {__version__}",
    )
    return p


def _looks_like_url(s: str) -> bool:
    """True when ``s`` is an http(s):// URL we should fetch via the network."""
    return s.startswith(("http://", "https://"))


def _default_cache_dir() -> Path:
    """``$XDG_CACHE_HOME/get-installer/`` (or platform fallback)."""
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "get-installer"
    return Path.home() / ".cache" / "get-installer"


def _default_registry_path() -> Path:
    """Locate ``registry.json``.

    Checks (in order):
      1. ``$GET_INSTALLER_REGISTRY`` env var
      2. ``./registry.json`` (cwd)
      3. Walk parents of this module looking for ``registry.json``

    Returns the cwd path even if missing — `Registry.load` raises a clean
    error citing the missing file.
    """
    env = os.environ.get("GET_INSTALLER_REGISTRY")
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd() / "registry.json"
    if cwd.is_file():
        return cwd
    here = Path(__file__).resolve()
    for parent in (*here.parents,):
        candidate = parent / "registry.json"
        if candidate.is_file():
            return candidate
    return cwd


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    ui = UI(
        assume_yes=args.yes,
        quiet=args.quiet,
        no_color=True if args.no_color else None,
    )

    # --registry can be a path or an HTTPS URL.
    registry_arg = args.registry
    auth_token = args.auth_token or os.environ.get("GET_INSTALLER_TOKEN")
    cache_dir = args.cache_dir or _default_cache_dir()

    try:
        if registry_arg and _looks_like_url(registry_arg):
            # Use a tiny pre-load of the local registry (if any) to read
            # access_control.allowed_origins; then enforce it on the URL fetch.
            allowed_origins: tuple[str, ...] = ()
            fallback = _default_registry_path()
            if fallback.is_file():
                try:
                    pre = Registry.load(fallback)
                    allowed_origins = pre.access_control.allowed_origins
                except ConfigError:
                    pass
            registry = Registry.from_url(
                registry_arg,
                auth_token=auth_token,
                fallback_path=fallback if fallback.is_file() else None,
                cache_dir=cache_dir,
                cache_max_age_seconds=0 if args.refresh else 300,
                allowed_origins=allowed_origins,
            )
        else:
            registry_path = Path(registry_arg) if registry_arg else _default_registry_path()
            registry = Registry.load(registry_path)
    except ConfigError as e:
        ui.fail(f"registry error: {e}")
        return 2

    if args.list:
        _print_listing(ui, registry)
        return 0

    if not args.product:
        ui.fail("--product is required (or --list to see what's available)")
        return 2

    try:
        config = registry.resolve(
            args.product,
            args.version,
            platform=current_platform(),
            allow_deprecated=args.allow_deprecated,
            allow_unsupported=args.allow_unsupported,
        )
    except (ConfigError, ResolutionError) as e:
        ui.fail(str(e))
        return 2

    if config.is_deprecated:
        ui.warn(f"version {config.version} is DEPRECATED")
        if config.status_reason:
            ui.detail(config.status_reason)
    elif config.is_unsupported:
        ui.warn(f"version {config.version} is UNSUPPORTED (override active)")
        if config.status_reason:
            ui.detail(config.status_reason)

    installer = Installer(
        config,
        ui=ui,
        allow_root=args.allow_root,
        dry_run=args.dry_run,
        with_python=args.with_python,
        rate_limits=registry.rate_limits,
        access_control=registry.access_control,
    )
    report = installer.run()
    return 0 if report.success else 1


def _print_listing(ui: UI, registry: Registry) -> None:
    ui.header(
        f"Registry: {registry.source_path}",
        f"updated {registry.registry_updated}  schema v{registry.schema_version}",
    )
    for product in registry.list_products():
        ui.print(f"\n{ui.BOLD}{product.name}{ui.RESET}  {ui.DIM}— {product.summary}{ui.RESET}")
        ui.print(f"  default: {product.default_version}")
        ui.print(f"  platforms: {', '.join(product.supported_platforms)}")
        ui.print("  versions:")
        for v in product.available_versions:
            entry = registry.products[product.name]["versions"][v]
            status = entry.get("status", "current")
            badge = "" if status == "current" else f" [{status}]"
            ui.print(f"    - {v}{badge}")


if __name__ == "__main__":
    sys.exit(main())
