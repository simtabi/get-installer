# Contributing to get-installer

Thanks for considering a contribution. This file captures the rules
that keep the codebase consistent.

## Read first

- [`SPEC.md`](SPEC.md): design spec + standing prompt for any
  coding agent. Read it end-to-end before opening a PR.
- [`docs/security.md`](docs/security.md): threat model. Required
  reading for changes touching `verify.py`, the bootstrap scripts,
  or anything network-facing.

## Development setup

```bash
git clone https://github.com/simtabi/get-installer
cd get-installer
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q
ruff check src tests scripts
mypy src/get_installer scripts
python scripts/bundle.py --check
```

All four must be green on every PR. CI runs them on macOS + Ubuntu +
Windows × Python 3.10 / 3.11 / 3.12 / 3.13.

## Architecture rules

These keep the surface area small and predictable.

1. **Stdlib only.** No runtime dependencies. Dev-tools (pytest, ruff,
   mypy) live under `optional-dependencies.dev`.
2. **The Python core is parameterised by `registry.json`.** No
   per-product logic in `src/`. New behaviour goes in the schema +
   the engine, not in special-cased branches.
3. **Bootstrap launchers stay thin.** `bootstrap/install.sh` and
   `install.ps1` only: detect Python, download `installer.py` +
   `registry.json`, verify SHA, hand off. All business logic lives
   in Python.
4. **Reproducibility.** `scripts/bundle.py` must produce
   byte-identical output for the same source. The build timestamp
   lives in the sidecar `installer.py.buildinfo.json`, not the
   bundle body.
5. **Security-first defaults.** New features default to the more
   restrictive option. `--allow-X` flags exist for the loose path,
   never the reverse.
6. **Access controls go through `verify.py`.** Anything that
   touches bearer tokens, signed-URL expiry, or HTTPS fetches must
   route through the helpers in `verify.py`. Don't reimplement
   `Authorization` header construction or `urllib.parse` checks
   inline. New auth kinds (basic, OAuth) extend `verify.py`, not
   `config.py` or `installer.py`.
7. **Per-product `access` is opt-in.** Public products omit the
   block. Adding `access.auth.required=true` is a breaking change
   from the user's perspective (their old `--auth-token`-less
   command stops working); bump the product's version and document
   it in the changelog the registry serves.

## Coding conventions

- `mypy --strict` clean. Prefer `Path` over `str` for filesystem paths.
- `ruff check` clean with the selected ruleset.
- Tests live in `tests/`. Use `tmp_path` for filesystem state. Never
  write to `~/.claude/`, `~/.config/`, or any real user path from a
  test.
- Docstrings on the class and every public method.
- No `# type: ignore` without a one-line comment explaining why.

## Commit messages

- Imperative subject ≤ 72 chars.
- Body explains why, not what.
- No emoji, no `Co-Authored-By` trailers (unless asked).
- AI-tells (`leverage`, `seamless`, `essentially`, `note that`,
  `simply,`, `comprehensive`, `robust`) are blocked. Write plainly.

## Multi-arch by default

Every container image we publish (every Dockerfile, every release
artefact) must build for `linux/amd64` AND `linux/arm64`. See
[`SPEC.md` Phase K](SPEC.md#phase-k--containerization--portable-deployment-multi-arch).

## What goes in this repo

- The reusable installer engine + bootstrap launchers.
- Per-project `registry.json` only as a dev fallback; the real
  registry is served from `get.simtabi.com`.

## What does NOT go in this repo

- The Phase M sibling repo (Laravel admin + REST API + Inertia + React
  + OAuth). That lives at
  `https://github.com/simtabi/get-installer-admin` (to be created).
- Personal / customer registries. Customers vendor this folder into
  their own private repo + edit their own `registry.json`.

## Release process

Tag-driven. Bump `pyproject.toml::project.version`, update
`CHANGELOG.md`, commit, tag `vX.Y.Z`, push the tag. CI handles PyPI
trusted-publishing + bundle SHA + GitHub Release asset upload.

## Reporting bugs

Open an issue with:

- What you ran (exact command line)
- What happened (output + exit code)
- What you expected
- `get-installer --list` + `get-installer --product NAME --dry-run` output
- Python version, OS, arch (`uname -m`)

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). Do not file public issues for
disclosures.
