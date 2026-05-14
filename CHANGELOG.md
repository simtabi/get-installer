# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added: Phase L (signed + auth + rate-limited install URLs)

Registry-driven distribution can now declare per-product access
controls for private / enterprise / domain-locked channels. Three
orthogonal mechanisms compose:

- **Bearer-token auth**: `access.auth.kind="bearer"`, optional
  `required=true`, custom `env_var` and `hint_url`. Token resolves
  CLI > product-env > `$GET_INSTALLER_TOKEN`. Sent as
  `Authorization: Bearer <token>` header; never in URL query.
  `verify.require_auth_token()` raises with a helpful no-token error
  citing the env-var name and the hint URL.
- **HMAC-SHA256 pre-signed URLs**: `access.signed.algorithm` plus
  `query_param`, `expires_param`, `max_skew_seconds`. The installer
  verifies expiry locally (`verify.check_signed_url()`); signature
  itself is server-issued and not re-verified client-side. Matches
  AWS / GCS / Cloudflare R2 pre-signed conventions.
- **Server-side rate-limit hint**: `access.rate_limit_hint` is
  documentation only; the server enforces real limits. Client-side
  429 + `Retry-After` handling was already in `verify.fetch_https`.

Schema (`schemas/registry.schema.json`) gains the `access` block on
products. New public types: `AuthAccess`, `SignedAccess`,
`ProductAccess` (all on `get_installer.*`). `InstallConfig.access`
field exposes the parsed declaration.

Installer flow:

- New `Installer._phase_validate_access` step runs after path /
  command checks. Surfaces auth + signed URL expectations to the
  user before the plan confirmation.
- `--auth-token` already plumbed via `Registry.from_url` for the
  registry fetch; now also passed into `Installer(auth_token=...)`.

Design doc: [`docs/security.md`](docs/security.md) Phase L section
documents the threat model deltas, token resolution order, what's
out of scope (mutual TLS, basic auth, OAuth, token refresh).

22 new tests (verify + config). 87 to 109 pass.

### Added: Homebrew tap distribution channel

- `templates/homebrew-formula.rb.template`: scaffold for the
  `simtabi/homebrew-tap` formulae. Includes placeholders documented
  inline and a `test do` block with version-assertion stub.
- `docs/distribution/homebrew.md`: walks the one-time tap setup
  (`brew tap-new`, `brew create --python`,
  `brew update-python-resources`) plus the release-time workflow that
  bumps the formula on every tag.
- Ported from `simtabi/shimkit/installer/homebrew-formula.rb.template`,
  generalized so any product in `registry.json` can land in the tap.

### Added: bootstrap `--bootstrap-uv` flag

- `bootstrap/install.sh` accepts `--bootstrap-uv` for users on a
  machine with no Python 3.10+ and no uv. Opt-in only; curl-pipes
  Astral's installer (`https://astral.sh/uv/install.sh`) over
  HTTPS+TLS1.2, then runs `uv python install 3.10` and re-resolves
  the interpreter. Complements the existing `--with-python` Python-
  side flag (which requires uv to already be present).
- Without `--bootstrap-uv`, the no-Python error message now lists
  all three install options (uv / pipx / Python) with their URLs,
  matching the friendly fail pattern from shimkit's installer.
- Two new tests in `tests/test_bootstrap_launchers.py`: stub-PATH
  drives the no-Python branch and asserts every URL surfaces; flag
  presence asserts parse-clean.

### Added: bootstrap test coverage (closes §5 I12 + I13)

- `tests/test_bootstrap_launchers.py`: 6 tests covering both launcher
  syntax (`bash -n`, `sh -n`, `pwsh` parse) and end-to-end flow
  against a local HTTP server: SHA-pin match succeeds, SHA-pin
  mismatch aborts BEFORE running `installer.py`, no-pin path warns
  and proceeds.
- `bootstrap/install.sh` gained `INSTALLER_PROTO_OVERRIDE` env var
  (test-only) so the fixture can serve over local HTTP. Loud-warns
  to stderr when set so production usage is visible.

### Added: CI: ARM + reproducibility + Docker multi-arch build

- `.github/workflows/ci.yml` matrix expanded to:
  `ubuntu-latest` (amd64), `ubuntu-24.04-arm` (arm64),
  `macos-latest` (Apple Silicon), `macos-13` (Intel), `windows-latest`.
  Coverage on every PR for amd64 + arm64 + Intel macOS.
- New `bundle` job step verifies byte-reproducibility by building
  twice and `cmp -s`-ing the output. Fails the workflow if the bundle
  drifts (catches future regressions of the timestamp-in-body kind).
- New `docker-multiarch` job builds the Dockerfile for both
  `linux/amd64` and `linux/arm64` via buildx + QEMU on every PR.

### Added: multi-arch + repo essentials

- `Dockerfile` now declares `BUILDPLATFORM`, `TARGETPLATFORM`,
  `TARGETARCH` build ARGs and uses `--platform=$TARGETPLATFORM` on the
  `FROM` line. Builds for `linux/amd64` AND `linux/arm64` from the
  same recipe.
- `scripts/build-multiarch.sh`: buildx wrapper that sets up the
  builder, handles `--load` vs `--push`, and detects host arch for
  local single-arch loads.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
  `SECURITY.md` (disclosure to `opensource@simtabi.com`), and
  `.editorconfig` added to match the Simtabi-org required-files
  baseline.
- `MANIFEST.in` for belt-and-braces sdist-content control.
- SPEC.md Phase K rewritten as "Containerization + portable
  deployment (multi-arch)" with a hard requirement that every image
  ships as a manifest list covering both `linux/amd64` and
  `linux/arm64`.

### Added: Phase C (remote registry source)

- `Registry.from_url(url, *, auth_token, fallback_path, cache_dir,
  cache_max_age_seconds, allowed_origins, timeout)`: loads a
  registry from an HTTPS URL with TTL'd disk cache, falls back to
  a local file on fetch failure, enforces the access-control
  origin allowlist.
- `verify.fetch_https` gained an `extra_headers` parameter for
  authenticated requests. Values containing CR/LF raise
  `SecurityError` (HTTP header-injection guard).
- CLI flags `--auth-token` (also reads `$GET_INSTALLER_TOKEN`),
  `--cache-dir`, `--refresh`. `--registry` now accepts both a path
  and an `https://` URL.
- 11 new pytest cases in `tests/test_remote_registry.py`.

### Changed

- `--registry` type changed from `Path` to `str` so URLs work.
  Behaviour for path inputs is unchanged.

### Fixed

- §5 issue **I11**: `allowed_origins` allowlist was dead code (no
  caller of `verify.fetch_https` from the Python side). Resolved by
  Phase C: `Registry.from_url` is now the live caller and passes
  the allowlist through.

## [0.1.0] - 2026-05-14

Initial release as a standalone project. Previously shipped inside
`simtabi/claude-configs` at `installer/`.

### Added
- Registry-driven `curl | sh` installer for distributing Simtabi (and
  vendor-able to any) dev tools.
- Schema v2 registry with multi-product, multi-version layout.
- Per-version `status` (`current` / `deprecated` / `unsupported` /
  `yanked`) with policy enforcement.
- `Journal` rollback / garbage-collector for clean abort on signal or
  exception.
- Bootstrap launchers: POSIX `install.sh` (sh-compatible) +
  PowerShell `install.ps1`.
- `--yes`, `--dry-run`, `--allow-root`, `--with-python`,
  `--no-color`, `--list` CLI flags.
- Rate-limiting + DDoS protection (exponential backoff with jitter,
  Retry-After respect, wall-clock deadline).
- Access control: HTTPS-only, `allowed_origins` allowlist, refuse-root,
  `0700` temp dirs, `0600` logs, `O_CREAT|O_EXCL` against TOCTOU
  symlink hijacks.
- Cross-platform: macOS, Linux, Windows wherever Python ≥ 3.10 runs.
- 43-case pytest suite.

### Renamed (vs the previous `installer/` subproject)
- Project: `installer` → `get-installer`.
- Python module: `installer.core` → `get_installer`.
- CLI: `simtabi-installer` → `get-installer`.
- Schema: `install.schema.json` → `registry.schema.json`.

### Pending (see [`docs/SPEC.md`](docs/SPEC.md))
- Remote API registry source (DB-backed; JSON as fallback).
- Multi-forge metadata in the registry (GitHub / GitLab / Bitbucket /
  Gitea / generic git).
- Domain-locked / enterprise / government tenancy.
- Signed releases (sigstore or GPG).
- Bundle script for vendoring as a single file.
- Web UI / admin panel.
- Mirror support.
