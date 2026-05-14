# Security Policy

## Supported versions

Only the latest minor release of `get-installer` receives security
fixes. Older versions are not patched. See
[`CHANGELOG.md`](CHANGELOG.md) for the current release.

| Version | Supported |
|---|---|
| 0.1.x | ✓ |
| < 0.1 | ✗ |

## Reporting a vulnerability

**Do not** open a public GitHub issue for security problems.

Email disclosures to: **`opensource@simtabi.com`**

PGP key fingerprint: *to be published in `docs/security.md` § Signing*.

We respond within **3 business days** to acknowledge receipt and
within **30 days** with a fix-or-mitigation plan.

## What's in scope

- The installer's Python core (`src/get_installer/`).
- The bootstrap launchers (`bootstrap/install.sh`, `install.ps1`).
- The bundle script (`scripts/bundle.py`) and its output.
- The static-CDN Dockerfile + nginx config.
- The registry schema (`schemas/registry.schema.json`).

## What's out of scope

- Vulnerabilities in third-party packages the installer installs.
  Those should be reported to the upstream maintainer; we'll
  yank/deprecate the affected version in the registry once a
  disclosure becomes public.
- Issues in the Phase M sibling admin repo (`get-installer-admin`).
  That repo has its own `SECURITY.md`.
- The customer's own infrastructure (their CDN, their DB, their
  Cloudflare account). We document hardening but don't own the
  deployment.

## Threat model

See [`docs/security.md`](docs/security.md) for the full threat model
and mitigations. Headline guarantees the installer makes:

- HTTPS-only for every Python-side fetch, with an
  `access_control.allowed_origins` allowlist.
- TOCTOU-safe writes (`O_CREAT | O_EXCL` + `0600` mode on every
  installer-owned file).
- Refuse-root by default; `--allow-root` is the explicit override.
- Rate-limited retries with exponential backoff + Retry-After
  respect.
- Yanked-version hard stop (release-revocation channel).
- Journaled rollback on signal or unhandled exception.

## Disclosure timeline

For confirmed issues:

1. Day 0: report received, acknowledged.
2. Day 0-7: triage + reproduce.
3. Day 7-30: fix + test + ship.
4. Day 30+: public advisory (GitHub Security Advisory) once a fixed
   version is available.

Researchers reporting in good faith are credited in the advisory
unless they ask to remain anonymous.
