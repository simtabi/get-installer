# get-installer

[![CI](https://github.com/simtabi/get-installer/actions/workflows/ci.yml/badge.svg)](https://github.com/simtabi/get-installer/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/get-installer.svg)](https://pypi.org/project/get-installer/)
[![Python](https://img.shields.io/pypi/pyversions/get-installer.svg)](https://pypi.org/project/get-installer/)
[![License](https://img.shields.io/github/license/simtabi/get-installer.svg)](LICENSE)

A reusable, **registry-driven `curl | sh`-style installer** for
distributing developer tools across public OSS, private enterprises,
universities, and government / domain-locked contexts.

> Pronounced "get installer": same words as the URL `get.simtabi.com`.
> The technique is also called **one-line installer**, **bootstrap installer**,
> or **distribution channel** (see [`SPEC.md` §0](SPEC.md#0--project-identity-locked)).

```bash
# POSIX (macOS / Linux / WSL / Git-Bash)
sh -c "$(curl -fsSL https://get.simtabi.com/install.sh)" -- --product claude-configurator

# PowerShell (Windows)
irm https://get.simtabi.com/install.ps1 | iex
```

---

## Table of contents

- [Why this exists](#why-this-exists)
- [Quick start](#quick-start)
- [What ships in the box](#what-ships-in-the-box)
- [URL layout at `get.simtabi.com`](#url-layout-at-getsimtabicom)
- [Project layout](#project-layout)
- [Security posture](#security-posture)
- [Documentation](#documentation)
- [Run from source](#run-from-source)
- [Tests](#tests)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why this exists

Distributing developer tools is a solved problem **only when the tool is
already on PyPI / Homebrew / apt / a package store**. For everything
else (fresh-machine bootstrap, mixed-OS install, on-prem enterprise
catalogues, university course toolkits, government-domain-locked
software) the de-facto pattern is `curl | sh`, hand-rolled per project.

This project gives you that pattern **once**, hardened and reusable:

- **One Python core** that drives every install.
- **JSON registry** (with optional REST-API source) declares products,
  versions, install methods, prompts, post-install steps.
- **Thin shell launchers** for the one-liner UX (`install.sh`,
  `install.ps1`).
- **Drop-in vendoring**: copy this folder + edit `registry.json` +
  publish. Done.
- **Hardened by default**: refuses root, HTTPS-only, origin allowlist,
  rate-limited, journaled rollback on signal/error, 0600 modes on
  every artefact.

Reference implementations this borrows patterns from: `rustup` (the
gold-standard one-liner), `Homebrew` (prompt-before-privileged-step),
`Docker get.docker.com` (distribution-aware), `uv` install (Python
bootstrap fallback), `k3s` (service installer).

## Quick start

```bash
get-installer --list                                # see what's available
get-installer --product claude-configurator         # install latest default version
get-installer --product claude-configurator --version 0.2.0 --yes
get-installer --product claude-configurator --dry-run
```

When used via the one-liner, the bootstrap script downloads the
Python core into a 0700-mode temp dir, verifies its SHA256 (when
pinned), and hands off to Python. Body bytes flow URL → disk; no
shell-eval of fetched content.

## What ships in the box

| Capability | Provider |
|---|---|
| Multi-product registry (schema v2) | `registry.json` + `schemas/registry.schema.json` |
| Per-version `status` enforcement (`current` / `deprecated` / `unsupported` / `yanked`) | `src/get_installer/config.py:Registry.resolve` |
| 7-phase install flow with TTY output | `src/get_installer/installer.py:Installer.run` |
| Garbage collector / rollback | `src/get_installer/journal.py:Journal` |
| HTTPS-only origin-allowlisted fetches | `src/get_installer/verify.py:fetch_https` |
| Rate-limit + DDoS protection | `src/get_installer/verify.py:fetch_https` |
| Refuse-root + PATH-injection guard | `src/get_installer/verify.py` |
| Optional `uv python install` bootstrap | `src/get_installer/python_setup.py` |
| POSIX + PowerShell launchers | `bootstrap/install.{sh,ps1}` |
| 43-case pytest suite | `tests/` |

## URL layout at `get.simtabi.com`

```
https://get.simtabi.com/
├── install.sh                         POSIX bootstrap
├── install.ps1                        PowerShell bootstrap
├── installer.py                       Python core (single-file bundle)
├── installer.py.sha256                SHA256 of installer.py
├── registry.json                      Static fallback registry
├── api/v1/registry.json               Dynamic (DB-backed) registry
├── api/v1/products                    List products
├── api/v1/products/<product>/versions GET versions
├── <product>/install.sh               Convenience alias (sets --product)
├── <product>/<version>/install.sh     Version-pinned alias
└── orgs/<org>/...                     Multi-tenant subtrees (token-gated)
```

Customer-mirror domains follow the same path layout, e.g.
`https://get.<customer>.com/install.sh` resolves locally.

Full URL contract in [`SPEC.md` §2](SPEC.md#2--url-layout-at-getsimtabicom).

## Project layout

```
get-installer/
├── README.md                          you are here
├── SPEC.md                            design spec + standing agent prompt
├── LICENSE                            MIT
├── CHANGELOG.md
├── pyproject.toml
├── registry.json                      this project's registry (also dev fallback)
├── bootstrap/                         OS-specific launchers
│   ├── install.sh                     POSIX (sh-compatible)
│   └── install.ps1                    PowerShell 5+
├── src/
│   └── get_installer/                 the Python package (stdlib only)
│       ├── __init__.py
│       ├── __main__.py                CLI entry
│       ├── config.py                  Registry + version resolution
│       ├── installer.py               7-phase flow
│       ├── journal.py                 GC / rollback
│       ├── ui.py                      prompts + colour
│       ├── verify.py                  HTTPS + sha256 + rate limits + refuse-root
│       └── python_setup.py            --with-python via uv
├── schemas/
│   └── registry.schema.json           JSON Schema (authoritative)
├── tests/                             pytest suite
└── docs/
    ├── config-schema.md
    ├── security.md
    └── vendoring.md
```

## Security posture

The full threat model lives in [`docs/security.md`](docs/security.md).
Headline guarantees:

- **HTTPS-only** for every Python-side download. Refuses URLs outside
  the `access_control.allowed_origins` allowlist.
- **TOCTOU-safe writes**: `O_CREAT | O_EXCL` + 0600 mode on every
  installer-owned file.
- **Rate-limited**: bounded retries, exponential backoff with jitter,
  HTTP 429 Retry-After respect, wall-clock deadline.
- **Refuse-root by default**: no installer is allowed to silently
  elevate; `--allow-root` is the explicit override.
- **Yanked-status hard-stop**: registry can declare a version `yanked`;
  the installer refuses to proceed unconditionally.
- **Journal + rollback**: every state-changing step records an undo
  callback. Signal (SIGINT / SIGTERM) or unhandled exception triggers
  reverse-order rollback.
- **Per-product access controls** (Phase E foundation): registry can
  declare `access.auth` (bearer-token, with custom env var + hint
  URL) and `access.signed` (HMAC-SHA256 pre-signed URLs with local
  expiry verification). Wired end-to-end through CLI, schema,
  resolver, and the validate phase.

Pending hardening: SHA256-pinned bootstrap, sigstore signatures,
reproducible bundle output, full org-scoped tenancy. See
[`docs/SPEC.md` §4 Phase F + Phase H](docs/SPEC.md#phase-f--signed-releases)
and [`docs/security.md`](docs/security.md) for the full threat model.

## Documentation

| Doc | Covers |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | **The spec + standing agent prompt.** Read this first if you're contributing. |
| [`docs/config-schema.md`](docs/config-schema.md) | Registry shape: products, versions, prompts, post-install, rate limits, access control. |
| [`docs/security.md`](docs/security.md) | Threat model + mitigations. |
| [`docs/vendoring.md`](docs/vendoring.md) | How to drop this folder into another project. |
| [`docs/distribution/homebrew.md`](docs/distribution/homebrew.md) | Homebrew tap as a complementary distribution channel. |
| [`docs/distribution/docker.md`](docs/distribution/docker.md) | Docker image build + the PUID/PGID convention that fixes Linux volume-permission issues. |

## Run from source

```bash
git clone https://github.com/simtabi/get-installer
cd get-installer
pip install -e ".[dev]"

get-installer --list
get-installer --product claude-configurator --dry-run --yes
```

## Tests

```bash
pytest -q                              # 43 cases
ruff check src tests
mypy src/get_installer
```

## Roadmap

Phase-by-phase plan lives in [`SPEC.md` §4](SPEC.md#4--required-features-by-phase).
Headline phases:

| Phase | Topic | State |
|---|---|---|
| A | Hosting + URL contracts at `get.simtabi.com` | pending |
| B | Single-file `installer.py` bundle script | pending |
| C | Remote API registry source (DB-backed) | pending |
| D | Forge-aware metadata (PyPI / git / tarball / binary) | pending |
| E | Multi-tenant + domain-locked installs | pending |
| F | Signed releases (sigstore / minisign) | pending |
| G | Web admin UI (separate sibling repo) | out of scope here |
| H | Hardening + audit + reproducible bundle | pending |
| I | Catalogue mode (git package distribution) | pending |

## License

MIT. See [`LICENSE`](LICENSE).
