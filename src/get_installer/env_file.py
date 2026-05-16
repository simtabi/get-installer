"""Tiny stdlib-only ``.env`` loader (SPEC Phase L).

A minimal ``KEY=VALUE`` parser. Comments start with ``#``. Blank lines
are OK. Values may be quoted with ``"`` or ``'``; outer quotes are
stripped. No interpolation, no command substitution, no array values.

Precedence on conflict: env > .env. Loading a key that's already in
``os.environ`` is a no-op, so explicit ``EXPORT KEY=value`` in the
shell wins over the .env file. This matches Docker Compose / Foreman
semantics.

Used by the CLI in :func:`get_installer.__main__.main` to read a
``.env`` file before the first env-var lookup. The bundled
``installer.py`` does NOT call this loader: it's CLI-only, since the
bundle should stay zero-dependency and never touch the filesystem
beyond what its arguments name.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path | str | None = None) -> dict[str, str]:
    """Load a ``.env``-style file into ``os.environ`` (non-overriding).

    Search order when ``path`` is None:
    1. ``$GET_INSTALLER_ENV_FILE`` env var (explicit override)
    2. ``./.env`` in the current working directory
    3. give up; return an empty dict

    @param  path  explicit file path, or None for the default search.
    @return dict[str, str]  the keys that were actually applied to
                            ``os.environ`` (already-set keys are
                            omitted, since they were not changed).
    @raises FileNotFoundError when an explicit ``path`` is given and
                              missing. Default search misses are silent.
    """
    if path is None:
        env = os.environ.get("GET_INSTALLER_ENV_FILE")
        if env:
            path = Path(env)
        else:
            cwd_env = Path.cwd() / ".env"
            if cwd_env.is_file():
                path = cwd_env
            else:
                return {}

    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f".env file not found: {p}")

    applied: dict[str, str] = {}
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{p}:{lineno}: expected KEY=VALUE, got {raw!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.isidentifier() and not all(c.isalnum() or c == "_" for c in key):
            raise ValueError(f"{p}:{lineno}: invalid key {key!r}")
        value = value.strip()
        # Strip matching outer quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied
