#!/usr/bin/env python3
"""Bundle the ``get_installer`` package into a single ``installer.py``.

The bundle is what gets hosted at ``https://get.simtabi.com/installer.py``.
The bootstrap launcher downloads this single file, verifies its SHA256
(when pinned), and runs it directly with ``python3 installer.py``.

Strategy: concatenate every module under ``src/get_installer/`` in
dependency order (config -> ui -> journal -> verify -> python_setup ->
installer -> __main__), strip ``__future__`` re-imports, rewrite
``from .X import`` -> ``from __mod_X import``-style internal refs are
NOT needed because all the public names already live in a flat module.
We emit ONE module whose top-level namespace contains every public
symbol the original package exports.

Constraints:
  - Output is a Python 3.10+ file, stdlib only.
  - Reproducible: same source bytes in -> same bundle bytes out.
  - < 200 KB target.
  - SHA256 emitted alongside.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "get_installer"

# Order matters: each module is appended after its dependencies.
MODULE_ORDER = (
    "config",
    "ui",
    "journal",
    "verify",
    "python_setup",
    "installer",
    "__main__",
)


HEADER_TEMPLATE = '''\
#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# get-installer: single-file bundle
#
# Generated automatically. Do not edit. Modify ``src/get_installer/`` and run
# ``scripts/bundle.py`` to regenerate.
#
# Bundle version: {version}
# Source modules: {modules}
# Source sha256: {source_sha}
#
# The build timestamp lives in the sidecar ``installer.py.buildinfo.json``
# next to this file: keeping it out of the bundle body makes the bundle
# reproducible (same source bytes -> same bundle bytes).
# ----------------------------------------------------------------------------
"""Reusable installer for Simtabi dev tools: bundled single-file form.

This file is functionally equivalent to ``python -m get_installer``. It
exists so the bootstrap launcher can download one Python file from
``https://get.simtabi.com/installer.py``, verify its checksum, and run
it without a ``pip install`` step.

CLI: see ``--help``. Schema: see ``registry.json`` and the docs at
``https://opensource.simtabi.com/documentation/get-installer``.
"""

from __future__ import annotations

'''


FOOTER = '''

if __name__ == "__main__":
    raise SystemExit(main())
'''


def _collect_top_level_imports(source: str) -> set[str]:
    """Return every ``import X`` / ``from <abs.module> import Y`` at top level.

    Excludes intra-package (``from .X``) and ``__future__`` imports: those
    don't belong in the bundle.
    """
    out: set[str] = set()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                line = f"import {alias.name}"
                if alias.asname:
                    line += f" as {alias.asname}"
                out.add(line)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # intra-package
            module = node.module or ""
            if not module or module == "__future__":
                continue
            names = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in node.names
            )
            out.add(f"from {module} import {names}")
    return out


def _module_body_only(source: str) -> str:
    """Return source with top-level imports + module docstring stripped.

    Uses AST line numbers to slice: robust to multi-line imports like
    ``from .verify import (\n    A, B, C,\n)``.
    """
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    skip = set()  # line indices (0-based) to drop

    for node in tree.body:
        start = node.lineno - 1
        end = (node.end_lineno or node.lineno) - 1
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            # Module docstring
            for i in range(start, end + 1):
                skip.add(i)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for i in range(start, end + 1):
                skip.add(i)
        else:
            break  # first non-import / non-docstring node: stop scanning

    kept = "".join(line for i, line in enumerate(lines) if i not in skip)
    # Collapse leading blank lines for tidier output
    return kept.lstrip("\n")


def _version_from_init(init_source: str) -> str:
    m = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', init_source, re.MULTILINE)
    return m.group(1) if m else "0.0.0+unknown"


def _source_sha256(modules: list[tuple[str, str]]) -> str:
    """Hash the concatenated module SOURCE so callers can verify the input."""
    h = hashlib.sha256()
    for name, source in modules:
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(source.encode("utf-8"))
    return h.hexdigest()


def bundle(*, src_root: Path = SRC_ROOT) -> str:
    init_source = (src_root / "__init__.py").read_text(encoding="utf-8")
    version = _version_from_init(init_source)

    sources: list[tuple[str, str]] = []
    for name in MODULE_ORDER:
        p = src_root / f"{name}.py"
        if not p.is_file():
            raise FileNotFoundError(f"missing module: {p}")
        sources.append((name, p.read_text(encoding="utf-8")))

    source_sha = _source_sha256(sources)

    # Collect every top-level import across modules, dedupe + sort.
    all_imports: set[str] = set()
    for _, src in sources:
        all_imports.update(_collect_top_level_imports(src))
    sorted_imports = sorted(all_imports)

    body_parts: list[str] = []
    for name, src in sources:
        body = _module_body_only(src)
        if not body.strip():
            continue
        body_parts.append(f"\n# ---- get_installer.{name} ----\n\n{body}")

    # Rewrite the __version__ string in the bundle so the CLI reports it.
    # `installer.py --version-installer` should print the same version as the package.
    version_line = f'__version__ = "{version}"\n\n'

    header = HEADER_TEMPLATE.format(
        version=version,
        modules=", ".join(name for name, _ in sources),
        source_sha=source_sha,
    )

    return (
        header
        + "\n".join(sorted_imports)
        + "\n\n"
        + version_line
        + "".join(body_parts)
        + FOOTER
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--output", "-o",
        type=Path,
        default=REPO_ROOT / "dist" / "installer.py",
        help="Where to write the bundle (default: dist/installer.py)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Compile-check the output via py_compile and exit non-zero on failure.",
    )
    args = p.parse_args()

    text = bundle()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Write bytes (not text) so Windows doesn't translate LF -> CRLF and
    # produce a file whose on-disk SHA differs from the recorded one.
    payload = text.encode("utf-8")
    args.output.write_bytes(payload)

    sha = hashlib.sha256(payload).hexdigest()
    (args.output.parent / (args.output.name + ".sha256")).write_bytes(
        (sha + "\n").encode("utf-8")
    )

    # Build metadata in a sidecar: keeping it out of the bundle body
    # keeps the bundle byte-reproducible across builds.
    import json
    buildinfo = {
        "built_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha,
        "size_bytes": args.output.stat().st_size,
    }
    sidecar = args.output.parent / (args.output.name + ".buildinfo.json")
    sidecar.write_text(json.dumps(buildinfo, indent=2) + "\n", encoding="utf-8")

    size = args.output.stat().st_size
    print(f"wrote {args.output} ({size} bytes, sha256 {sha[:16]}...)")

    if args.check:
        import py_compile
        try:
            py_compile.compile(str(args.output), doraise=True)
        except py_compile.PyCompileError as e:
            print(f"compile-check failed: {e}", file=sys.stderr)
            return 1
        print("compile-check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
