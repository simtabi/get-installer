"""Simtabi reusable installer engine.

Stdlib-only Python. Parameterised by an ``registry.json``
(schema v2): a multi-product, multi-version registry the bootstrap
fetches and the user picks from with ``--product`` + ``--version``.

Layout:
    config.py          load + validate registry.json; resolve (product, version)
    ui.py              terminal output, prompts, colour
    journal.py         action ledger + rollback (the garbage collector)
    verify.py          HTTPS, sha256, refuse-root, PATH-injection guard
    python_setup.py    --with-python via uv (when Python is missing)
    installer.py       the main flow: consumes a resolved InstallConfig
    __main__.py        CLI entry point
"""

from __future__ import annotations

from .config import (
    AuthAccess,
    ConfigError,
    ContentRepo,
    InstallConfig,
    PostInstallStep,
    ProductAccess,
    ProductSummary,
    Prompt,
    Registry,
    ResolutionError,
    SignedAccess,
    current_platform,
)
from .installer import Installer, InstallReport
from .journal import Journal, JournalEntry
from .ui import UI
from .verify import SecurityError

__all__ = [
    "UI",
    "AuthAccess",
    "ConfigError",
    "ContentRepo",
    "InstallConfig",
    "InstallReport",
    "Installer",
    "Journal",
    "JournalEntry",
    "PostInstallStep",
    "ProductAccess",
    "ProductSummary",
    "Prompt",
    "Registry",
    "ResolutionError",
    "SecurityError",
    "SignedAccess",
    "current_platform",
]

__version__ = "1.0.0"
