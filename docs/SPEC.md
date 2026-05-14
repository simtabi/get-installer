# `get-installer`: design specification + agent prompt

> This file is **both** the design specification AND the standing prompt
> that future Claude Code sessions (and any other coding agent) load when
> they continue this project. It captures the full scope, the current
> state, every known issue / gap, and the work still to do.
>
> When invoked by an agent: read this file end-to-end, **state which
> phase you're about to work on**, then execute. If the user's request
> doesn't fit any phase, ask before extending the scope.

---

## 🔁 Session protocol (read before everything else)

Each session has a defined shape. Skipping any step costs more time
than it saves.

### Session start

1. **Read `SPEC.md` end-to-end** (this file). Capacity-cost is small;
   miscalibration cost is high.
2. **Run the audit checklist** in the section below. Report the 5-line
   summary as the first thing in your response.
3. **Read any project-state files** that exist:
   - `STATUS.md` (current sprint state, if present)
   - `~/.claude/projects/<slug>/memory/MEMORY.md` (cross-session memory)
   - The most recent entry in `CHANGELOG.md` (what shipped last)
4. **Restate the user's goal** in one sentence before any tool call.
   This is the cheapest hallucination-killer there is: if you got the
   goal wrong, the user corrects you before you've burned a turn.

### During the work

5. **Hallucination guard**: every claim about the codebase comes
   from a live `Read` / `Grep` / shell call in this session. Memory
   says what was true *when written*, not what's true *now*. Cite
   `path:line` everywhere you can. Phrases that signal you're
   guessing: "typically", "usually", "I believe", "around line ~",
   round numbers, paraphrases of code you haven't opened.

6. **Track progress**: use `TaskCreate` / `TaskUpdate` for anything
   beyond 3 steps. Mark `in_progress` *before* you start; `completed`
   *the moment* it's done, never batched.

7. **Watch for regressions**: after every non-trivial edit, run the
   relevant subset of the audit checklist. Don't accumulate a
   "I'll-run-tests-at-the-end" debt: failures discovered late cost
   double (the original work plus the retracing).

8. **Log failures**: when a step fails (test red, lint complaint,
   wrong assumption), record it in your reply immediately: what failed,
   what you tried, what you'll try next. Don't silently retry.

9. **Research before guessing**: when you need a fact you don't have
   from this session's reads (an API signature, a CLI flag's
   semantics, a spec version), use `WebFetch` to read the official
   docs first, then trusted blogs second, only then ask the user.
   Sources to prefer, by order of trust:
   - Official documentation site (`docs.<vendor>.com`, `developer.<vendor>.com`)
   - Project's own GitHub README / spec file
   - Tagged releases / CHANGELOG entries
   - Reputable blog posts (lobste.rs / HN front-page, the author's own site for project maintainers)
   - Stack Overflow answers with > 50 upvotes and a recent edit date
   - **Skip**: random Medium articles, content farms, AI-generated blog
     spam, anything paywalled, GitHub gists without context

10. **Clarifying questions**: when the user's ask is ambiguous *and*
    the wrong interpretation would cost > 5 minutes to undo, **ask
    once before doing the work**. Acceptable phrasing: a numbered
    list of options, each with the trade-off. Not acceptable: a
    Socratic chain.

### Session end

11. **Self-improvement loop**: before signing off, scan your own
    work and suggest:
    - SPEC updates (new findings → §5 issues; finished phases → mark
      `[x]`).
    - Prompt updates (this section): patterns you'd want the next
      agent to follow that aren't here yet.
    - Test gaps you noticed but didn't close.

12. **Hand-off summary**: last paragraph of the session covers:
    what changed (cite paths), what's still open (cite issue ids),
    what the next agent should pick up first.

### Failure modes that this protocol guards against

- **Drift between SPEC and codebase**: caught by step 2 + 11.
- **Hallucinated APIs / line numbers**: caught by step 5.
- **Half-applied changes**: caught by steps 6 + 7.
- **Silent retries that mask bugs**: caught by step 8.
- **Outdated knowledge baked into code**: caught by step 9.
- **Scope drift from misread requirements**: caught by step 4 + 10.

---

## 🔍 Audit checklist: run this FIRST every session

Before writing or modifying code, every agent loading this file must
run a status sweep and report findings inline. This is not optional;
it catches drift between this spec and the codebase before that drift
compounds.

The checklist:

1. **`pytest tests -q`**: must be green. If not, fix before anything else.
2. **`ruff check src tests scripts`**: must be clean. Same.
3. **`mypy src/get_installer scripts`**: must be clean (strict).
4. **`shellcheck bootstrap/install.sh deploy/build-aliases.sh`**: must be clean.
5. **`scripts/bundle.py --check`**: bundle still builds.
6. **CLI surface check**: run `python -m get_installer --help` and
   confirm the flags listed match `docs/config-schema.md`.
7. **README authority check**: `find . -name "README.md" -not -path
   "*/resources/*" -not -path "*/.venv/*" -not -path "*/.git/*"`: should
   return exactly **ONE** path (`./README.md`). Per-pack `details.md`
   under `resources/decisions/<pack>/` are fine; per-pack README.md
   files anywhere are not.
8. **Roadmap drift**: for each `[x]` item in §4, spot-check the
   referenced file/feature actually exists. For each `[ ]` item, spot-check
   it's actually not done.
9. **Security baselines**: quickly grep for:
   - `subprocess.run(.*shell=True` (zero matches expected)
   - `os.system\|eval\(` (zero matches expected)
   - URL fetches outside `verify.fetch_https` (zero matches expected)
   - `mode=0o7..` / `chmod` calls in non-test code: verify each is
     ≤ `0o644` for non-secret + `0o600` for journal logs / tmp files.
   - `access.auth.required=true` products: confirm
     `verify.require_auth_token` is on the path that fetches them.
   - `access.signed` products: confirm `verify.check_signed_url`
     runs on every URL the installer constructs.
10. **AI-tell prose check**: `grep -rniE 'leverage|seamless|essentially|note that|simply,|comprehensive|robust\b|delve into' docs/ README.md CHANGELOG.md` returns no real prose (only banned-list mentions are OK). Em-dash sandwich pattern (` — `) also zero in prose.

Report findings as a 5-line summary at the top of your first response,
THEN proceed with the actual user request.

---

## 0: Project identity (locked)

| Field | Value |
|---|---|
| Project | `get-installer` |
| Python module | `get_installer` |
| CLI command | `get-installer` |
| Distribution host (public) | `https://get.simtabi.com` |
| Repo (GitHub) | `https://github.com/simtabi/get-installer` |
| License | MIT, `Copyright (c) 2026 Simtabi LLC` |
| Min Python | 3.10 |
| Runtime deps | **none** (stdlib only) |
| Owner contact | `opensource@simtabi.com` |

The technique this project implements is widely called **`curl | sh`**,
**one-line installer**, **bootstrap installer**, or
**distribution channel**. The artefact it serves is an **install
script**; the system as a whole is a **distribution channel**. Names
worth knowing because reviewers, security researchers, and prospects
will use them.

Reference implementations to mirror patterns from (in order of how much
to copy): **rustup** (`sh.rustup.rs`), **Homebrew**
(`Homebrew/install`), **Docker** (`get.docker.com`), **k3s**
(`get.k3s.io`), **nvm** / **pyenv** / **volta** for shell-rc edits,
**uv** (`astral.sh/uv/install.sh`) for the bootstrap-with-Python
pattern.

## 1: Mission

A reusable, secure, versatile bootstrap installer for distributing
software packages across **public OSS**, **private enterprises**,
**universities**, and **government / domain-locked** contexts. One
generic Python core + thin shell launchers, parameterised by a
registry (JSON file *or* remote API), suitable for any organisation
that needs to distribute software safely with audit-friendly defaults.

This installer is intentionally **scope-broader than `claude-configurator`**:
its first user is `claude-configurator`, but the second, third, and
hundredth user are other Simtabi tools, third-party tools that vendor
this installer, and customer enterprises with private product
catalogues.

## 2: URL layout at `get.simtabi.com`

The canonical distribution channel. Static-file-CDN-friendly so it can
be served behind CloudFront / Fastly / equivalents.

```
https://get.simtabi.com/
├── install.sh                         POSIX bootstrap (generic: needs --product flag)
├── install.ps1                        PowerShell bootstrap
├── installer.py                       Python core (the bundled single-file artefact)
├── installer.py.sha256                SHA256 of installer.py (text file, one line)
├── installer.py.sig                   Optional sigstore / GPG signature
├── registry.json                      Static registry (fallback when API is down)
├── registry.json.sha256
├── api/                               Optional dynamic registry (DB-backed)
│   ├── v1/registry.json               Full snapshot (same shape as static)
│   ├── v1/products                    GET → list of product names
│   ├── v1/products/<product>          GET → product entry
│   ├── v1/products/<product>/versions GET → version list
│   ├── v1/products/<product>/versions/<version>  GET → version data
│   ├── v1/orgs/<org>/...              Multi-tenant, token-gated subtrees
│   └── v1/audit/install               POST → installer-side telemetry beacon (opt-in)
├── <product>/                         Convenience aliases (no --product flag needed)
│   ├── install.sh                     Sets product implicitly
│   ├── install.ps1
│   └── <version>/
│       ├── install.sh                 Pins --version too
│       └── install.ps1
├── orgs/<org>/                        Per-org curated views
│   ├── install.sh
│   ├── registry.json
│   └── ...
└── schemas/
    └── registry.schema.json           Authoritative JSON Schema
```

Mirror domains (customer enterprises): `https://get.<customer>.com/...`
with the same path layout. The installer's `--registry` flag takes
either a path or a URL, so mirrors are a deployment concern, not a
code concern.

## 3: Current state (as of this commit)

What is **done**:

1. Python core: `src/get_installer/{config,installer,journal,ui,verify,python_setup}.py`.
2. CLI: `python -m get_installer --product NAME [...]`.
3. Bootstrap launchers: `bootstrap/install.sh` (POSIX),
   `bootstrap/install.ps1` (PowerShell).
4. Registry schema v2 with multi-product / multi-version /
   `status`-driven gating.
5. 43-test pytest suite passing, ruff clean, mypy strict clean.
6. Docs: `README.md`, `docs/config-schema.md`, `docs/security.md`,
   `docs/vendoring.md`.
7. Standalone Python package: `pyproject.toml`, `LICENSE`, `CHANGELOG.md`,
   `.gitignore`.
8. Rate-limiting + access-control (allowed-origins, mode bits)
   configured via `registry.json`.
9. Garbage-collector / rollback via `Journal` + signal traps.

Known issues / gaps logged in §5.

## 4: Required features (by phase)

Each phase is **independently shippable**. An agent picking up this
spec should declare which phase it is working on before writing code.
Phases are roughly ordered by ROI; pick out of order only if the user
explicitly asks.

### Phase A: Hosting + URL contracts ✔ 2026-05-14

- [x] `bootstrap/install.sh` defaults to `https://get.simtabi.com`.
- [x] `bootstrap/install.ps1` defaults to `https://get.simtabi.com`.
- [x] Bootstrap scripts accept `INSTALLER_BASE_URL` env-override.
- [x] Per-product alias pattern documented (see
      `deploy/build-aliases.sh` which generates them at container
      build time from `registry.json`).
- [x] CDN deployment recipes documented in `aws.md` +
      `vps.md` + `cloudflare-tunnel.md`.

### Phase B: Bundle script (vendor-friendly single file) ✔ 2026-05-14

- [x] `scripts/bundle.py`: produces `dist/installer.py` from
      `src/get_installer/`.
- [x] Bundle preserves the public CLI: `python installer.py --list`
      etc. behave identically to `python -m get_installer --list`.
- [x] Bundle is single-file, ~59 KB (< 200 KB target).
- [x] **Reproducible**: timestamps live in the sidecar
      `installer.py.buildinfo.json`, not the bundle body. Running
      `bundle.py` twice yields byte-identical output. (Asserted in
      `tests/test_bundle.py:test_bundle_reproducible`.)
- [x] CI builds and uploads `installer.py` + `installer.py.sha256` on
      every tag: see `.github/workflows/release.yml`.
- [x] Bundle test suite (`tests/test_bundle.py`, 7 cases) runs the
      bundled file end-to-end.

### Phase C: Remote registry source (DB-backed) with JSON fallback ✔ 2026-05-14

- [x] `Registry.from_url(url, *, fallback_path, cache_dir, …)`:
      loads from an HTTPS URL with optional auth header.
      (`src/get_installer/config.py:Registry.from_url`)
- [x] On URL fetch failure, falls back to a local `fallback_path`
      with a stderr warning. If no fallback, raises `ConfigError`.
- [x] CLI: `--registry` accepts URL or path (auto-detected via
      `_looks_like_url`). `--auth-token` flag + `GET_INSTALLER_TOKEN`
      env var both supported. `--cache-dir` + `--refresh` flags.
- [x] Origin-allowlisted via `access_control.allowed_origins` from a
      local pre-load registry (closes §5 issue **I11**:
      `verify.fetch_https` now has a real caller through `from_url`).
- [x] Cache: validated responses are stashed at
      `$XDG_CACHE_HOME/get-installer/registry-<sha>.json` (mode
      0700/0600). TTL configurable (`cache_max_age_seconds`, default
      300 s). Stale + `--refresh` both force re-fetch.
- [x] Header injection guard: `extra_headers` values containing
      `\r` / `\n` raise `SecurityError` before any request is made.
- [x] 11 new tests in `tests/test_remote_registry.py` covering happy
      path, auth header, header-injection refusal, cache write/use/
      stale/refresh, fallback, missing-fallback, malformed JSON,
      allowlist enforcement.
- [ ] Server side (out of repo scope): document the expected
      schema under `docs/api.md`. Lives in Phase M sibling repo.

### Phase D: Forge-aware metadata (git packages)

Some products are distributed as **git repos / tags**, not PyPI
packages. Universities cataloguing research code, internal tooling,
private GitHub Enterprise / Bitbucket Server / GitLab self-hosted /
Gitea: these don't all push to PyPI. The registry should support:

- [ ] New `source` field on a version entry with discriminated union:
      `{type: "pypi", name, version}`,
      `{type: "git", url, ref, install_after_clone: [...]}`,
      `{type: "binary", urls: {<os-arch>: url, ...}, sha256: ...}`,
      `{type: "tarball", url, sha256, strip_components, install_after_extract}`.
- [ ] `install_method` becomes derived from `source.type` when
      `auto`.
- [ ] Git-source clones into a user-owned dir (`~/.local/share/<product>/`),
      checks out the pinned ref, then runs `install_after_clone`
      argv-list (e.g., `pip install -e .` or `make install`).
- [ ] Schema bump: this is a v3-compatible additive change if
      `source` is optional with PyPI as the default.
- [ ] Tests cover each source type with a mock subprocess.

### Phase E: Multi-tenant + domain-locked installs

For enterprise / government / university customers:

**Foundation ✔ 2026-05-14: per-product access controls**

- [x] `products.<name>.access.auth`: bearer-token requirement per
      product, with `env_var` and `hint_url`. Token resolution order:
      `--auth-token` > product env_var > `$GET_INSTALLER_TOKEN`.
      (`config.AuthAccess`, `verify.resolve_auth_token`,
      `verify.require_auth_token`)
- [x] `products.<name>.access.signed`: HMAC-SHA256 pre-signed URLs
      with configurable `query_param`, `expires_param`,
      `max_skew_seconds`. Client verifies expiry locally; signature
      itself is server-issued. (`config.SignedAccess`,
      `verify.check_signed_url`)
- [x] `products.<name>.access.rate_limit_hint`: documentation only;
      real limits enforced server-side. Client already honours 429 +
      `Retry-After` via `verify.fetch_https`.
- [x] `Installer._phase_validate_access`: surfaces auth + signed-URL
      expectations during validate phase, refuses when token required
      but missing.
- [x] Design + threat-model documented in `docs/security.md`.

**Tenant scoping (pending)**

- [ ] **Org-scoped registry view**: registry top-level can declare
      `tenancy: { "mode": "open" | "domain-locked" | "token-locked",
      "orgs": [...] }`. The installer enforces:
      - `domain-locked`: refuses unless the resolved hostname of
        `--registry` URL matches one of the org's allowed DNS suffixes.
      - `token-locked`: requires `GET_INSTALLER_TOKEN` and the server
        validates it. Today's per-product `auth.required` is the
        per-product analogue; tenant scoping generalises it.
- [ ] Per-org subtree in the registry: `orgs: { "<org-slug>": { products: {...} } }`.
- [ ] CLI `--org <slug>` selects the subtree. Without `--org`, the
      installer uses the top-level `products` (public) view.
- [ ] All org-scoped installs emit an opt-in audit beacon (`api/v1/audit/install`)
      if the server supports it. The beacon is **anonymised** by default
      (only product + version + result, no user data): opt-in to richer
      telemetry via `audit_telemetry` in the registry.
- [ ] Document the customer-mirror playbook in `docs/enterprise.md`.

### Phase F: Signed releases

Today the bootstrap supports an optional SHA256 pin. Sign properly:

- [ ] Optional **sigstore** signing of `installer.py` and `registry.json`
      via `cosign sign-blob`. Public-key verification via `cosign verify-blob`
      in the bootstrap.
- [ ] Alternative: **minisign** for projects that prefer it.
- [ ] Verification is **off by default** (the install runs without
      signatures present) and **opt-in via a flag** so the existing
      `curl | sh` UX survives. Once a customer enables signing,
      mismatch is fatal.
- [ ] Document key rotation + the signing pipeline in
      `docs/signing.md`.

### Phase G: Web UI / admin panel (separate deliverable)

Out of immediate scope but listed so a contributor knows where the line is:

- [ ] A small FastAPI + HTMX (or Astro / Svelte) admin app that
      manages the DB-backed registry: products CRUD, versions CRUD,
      status transitions, audit log viewer, org management.
- [ ] **Lives in a sibling repo** (`simtabi/get-installer-admin`),
      not here. This repo stays stdlib-only.
- [ ] The static `registry.json` is generated by the admin app and
      uploaded to the CDN nightly (and on demand).

### Phase H: Hardening + audit

Round of polish + a public threat-model review:

- [ ] **TOCTOU-safe writes**: every file the installer creates uses
      `O_CREAT|O_EXCL` (mostly done in `verify.py:fetch_https` and
      `journal.py:write_log`; audit every other write).
- [ ] **PATH-injection deeper check**: today we warn on world-writable
      PATH entries; add a refuse-mode flag that errors instead.
- [ ] **Detection of partial downloads**: the bootstrap script's
      atomic `mv` is good; document the mid-flight kill test
      (`set -euo pipefail` + kill `curl` after 10 KB and confirm no
      half-installed state).
- [ ] **Server-side `User-Agent` parity**: per the
      `curl | sh` criticism (see
      [idontplaydarts.com/2016/04/](https://www.idontplaydarts.com/2016/04/detecting-curl-pipe-bash-server-side/))
      the host MUST serve identical bytes regardless of UA. Document
      this as a deployment requirement and provide a CI check that
      fetches the install script with two UAs and diffs.
- [ ] **Reproducible bundle**: bundling the same source twice produces
      byte-identical output. Document. CI gate.

### Phase I: Forge package distribution (git-package catalogues)

For universities / orgs that catalogue git-based projects (research
code, internal tools), give them a way to declare their catalogue:

- [ ] Registry mode `catalogue`: products entries don't install; they
      list. `get-installer list` + `get-installer search`.
- [ ] Each catalogue product can have `forge: { type: github|gitlab|...,
      url, default_branch, license, topics: [...] }`.
- [ ] `get-installer fetch-source <product>` clones the product's source
      without installing anything. Useful for "show me the code".
- [ ] Document this mode in `docs/catalogue.md`.

### Phase J: CI/CD + release pipeline

Automated quality gates + artefact publishing. Lives in this repo's
`.github/workflows/`.

- [ ] `ci.yml`: runs on every push / PR:
      pytest + ruff + mypy + `scripts/bundle.py --check` on a matrix of
      `{ubuntu-latest, macos-latest, windows-latest} x {3.10, 3.11, 3.12, 3.13}`.
- [ ] `release.yml`: runs on `v*.*.*` tags:
      builds the wheel + the single-file `installer.py` bundle +
      computes SHAs + uploads as GitHub Release assets + publishes the
      wheel to PyPI via OIDC trusted publishing.
- [ ] `cdn-sync.yml`: on tag push, syncs the release assets
      (`installer.py`, `installer.py.sha256`, `install.sh`,
      `install.ps1`, `registry.json`) to the `get.simtabi.com` object
      store. (Credential: scoped GitHub Actions secret; rotate
      quarterly.)
- [ ] `dependabot.yml` already-style: weekly Monday 06:00 NY for
      `pip` + `github-actions`.
- [ ] Branch-protection guidance documented in `docs/release.md`.

### Phase K: Containerization + portable deployment (multi-arch)

**Hard requirement: every container image we publish is multi-arch.**

Containers must run on:

| Architecture | Docker platform tag | Example hosts |
|---|---|---|
| 64-bit Intel/AMD | `linux/amd64` | Most VPS / cloud VMs / Intel + AMD desktops |
| 64-bit ARM | `linux/arm64` (a.k.a. `aarch64`) | Apple Silicon (M1/M2/M3/M4), AWS Graviton, Ampere, Raspberry Pi 4+ 64-bit, modern Android servers |
| 32-bit ARM | `linux/arm/v7` | Older Raspberry Pi, embedded Linux | *(best-effort; ship when there's a real demand signal)*

Same rule applies to **Linux-installed** binaries (i.e., `pipx install`
on a server): they must work identically on AMD64 and ARM64. Python
itself is arch-agnostic, but any tool we ship that uses C extensions
must publish wheels for both arches.

#### Build rules

- [ ] `docker buildx build --platform linux/amd64,linux/arm64 …` is the
      default build command. Document in `vps.md` and the CI.
- [ ] Dockerfile uses `--platform=$BUILDPLATFORM` + `$TARGETPLATFORM`
      ARGs for any cross-compilation work. Don't hardcode an arch in
      `FROM` lines.
- [ ] Base images: prefer official multi-arch images (`ubuntu:26.04`,
      `python:3.12-slim`, `node:22-alpine`: all multi-arch on Docker
      Hub). Pin by SHA digest in production (`@sha256:…`) so
      `ubuntu:26.04` updates don't silently bump the build.
- [ ] Refuse arch-specific binary downloads inside the Dockerfile
      without arch detection: use `uname -m` / `$TARGETARCH` to pick
      the right artefact.
- [ ] CI release pipeline pushes a **manifest list** to the registry
      so `docker pull` Just Works on any host arch: no `--platform`
      needed by the consumer.
- [ ] Smoke test on at least one ARM64 host before tag (GitHub-hosted
      `ubuntu-24.04-arm` runners, or a self-hosted Apple Silicon
      runner).



The end goal: a single Docker image that runs the **server side** (DB,
API, web UI) of the distribution channel. The **client** (this
installer) doesn't need a container: it runs on the user's machine.
But for the operator running `get.simtabi.com`, the server-side stack
should be one `docker compose up` away.

Stack:

| Layer | Choice |
|---|---|
| Base image | `ubuntu:26.04` (LTS), `ubuntu:24.04` as fallback if 26.04 not yet on Docker Hub |
| Database | PostgreSQL 17+ (latest stable) |
| Runtime | Python 3.12 + PHP 8.3 (PHP for the Laravel admin in Phase M) |
| Web | nginx 1.27 + PHP-FPM |
| Process supervisor | Supervisor (Ubuntu's `supervisor` package) |
| Networking | Cloudflare Tunnel (zero-trust, no inbound ports) **or** direct VPS with Caddy/Let's Encrypt **or** AWS ELB + ACM |
| DNS / SSL | Cloudflare DNS + auto-SSL via the Tunnel; Let's Encrypt elsewhere |
| Dev domain | `*.test` resolved via dnsmasq (mkcert for trusted local TLS) |

Artefacts to add in this repo:

- [ ] `Dockerfile`: Ubuntu 26.04 LTS base + Python 3.12 + supervisor.
      Bundles the static `registry.json` + `installer.py` + `install.{sh,ps1}`
      and serves them via nginx at port 80 inside the container.
      Suitable for the read-side of `get.simtabi.com`: pure CDN
      semantics, no DB needed.
- [ ] `Dockerfile.api`: adds Postgres client + Laravel admin
      (Phase M). Bigger, includes PHP-FPM + composer + node for
      the admin's Vite build. **Optional**: customers that don't
      need the dynamic API skip this entirely and just use the
      static Dockerfile.
- [ ] `docker-compose.yml`: dev stack: postgres + the API container
      + the static container + a Cloudflare Tunnel sidecar. Reads
      `.env` for secrets.
- [ ] `docker-compose.prod.yml`: production overlay: removes dev-only
      flags, enables health checks, sets resource limits, swaps to
      named volumes.
- [ ] `.env.example`: every supported env var, commented, **with no
      real secrets**. Copy-pasted into `.env` (gitignored) per deploy.
- [ ] `supervisor.conf`: defines processes: nginx, php-fpm,
      cloudflared, the api worker. Each with retry + auto-restart +
      structured-log redirection.
- [ ] `cloudflare-tunnel.md`: recipe for `cloudflared tunnel
      create` + DNS routing.
- [ ] `aws.md`: ECS / Fargate / S3 recipes.
- [ ] `vps.md`: straight `apt install` + `docker compose`
      recipe for a single Ubuntu host (the "I have one $5 VPS" path).
- [ ] `dev-test-domain.md`: mkcert + dnsmasq for local
      `*.test` development.

### Phase L: Configuration via `.env`

For the server-side stack (Phase K) and any future deployable bits:

- [ ] `.env.example` is the authoritative list of supported variables.
- [ ] At runtime the server reads `.env` (12-factor): never commits a
      populated `.env` (gitignored).
- [ ] `.env.example` is **also** the schema for a `validate-env.py`
      script that checks the deploying user's `.env` against it (refuses
      to start if required vars are missing).
- [ ] Documented variables: minimum viable set:
      - `GET_INSTALLER_DB_URL`: Postgres DSN (`postgres://user:pass@host:5432/get`)
      - `GET_INSTALLER_BASE_URL`: public origin (e.g. `https://get.simtabi.com`)
      - `GET_INSTALLER_ALLOWED_ORIGINS`: comma-separated allowlist
      - `GET_INSTALLER_TOKEN_SECRET`: HMAC secret for org tokens
      - `GET_INSTALLER_AUDIT_LOG_PATH`: where audit beacons land
      - `CLOUDFLARE_TUNNEL_TOKEN`: for the cloudflared sidecar
      - `PG_USER` / `PG_PASS` / `PG_DB`: Postgres dev creds
      - `LARAVEL_APP_KEY`: set by `artisan key:generate`
      - etc: see `.env.example` once it lands.

### Phase M: Sibling repo: `get-installer-admin` (Laravel 13 + Inertia + React + REST API + OAuth)

The web UI + REST API + DB management. **Does not live in this repo;
this repo stays stdlib-Python only.** But the SPEC tracks it here so
the system is described in one place.

Stack:

| Layer | Choice |
|---|---|
| Server framework | **Laravel 13** (latest stable) |
| Server language | **PHP 8.3+** |
| Database | **PostgreSQL 17+** (Eloquent ORM) |
| Frontend | **React 18+** via **Inertia.js** (server-driven SPA: Laravel routes, React components, no separate frontend repo) |
| Component library | **shadcn/ui** + **Tailwind CSS 4** |
| State / data fetching | **TanStack Query** for the REST surface; Inertia handles page-level data |
| Build / bundler | **Vite 6** |
| API style | **REST** with explicit JSON resources at `/api/v1/...` (separate from the Inertia routes which serve the SPA) |
| AuthN | **OAuth 2.1 / OIDC** via Laravel **Socialite**: GitHub, GitLab, Google, Microsoft Azure AD (enterprise SSO), generic OIDC for self-hosted IdPs. Personal access tokens via **Sanctum**. Hardware keys / WebAuthn via `laravel-webauthn`. |
| AuthZ | **Spatie laravel-permission** for role-based + scope-based access; per-org tenancy via `tenancy_for_laravel` or first-party scope. |
| Background jobs | **Laravel Horizon** on **Redis 7+** |
| Mail | SES + Postmark drivers configured |
| Observability | **Laravel Pulse** for app metrics; **OpenTelemetry** for traces (OTel collector sidecar) |

#### Why Inertia + React (vs. Filament / Livewire)

- **Filament 3** was strong but limits us to its component DSL; some
  enterprise customers want their own white-labelled admin built on the
  same backend.
- **Inertia + React** gives a real SPA UX without the cost of two
  codebases: the admin and any white-labelled portals share routes,
  controllers, and policies.
- **REST stays first-class**, separate from the Inertia routes: the
  installer + customer scripts / Terraform / SDKs all use REST; only
  the admin UI uses Inertia.

#### Routes

```
GET  /                                          → admin SPA (Inertia)
GET  /dashboard                                 → SPA route
GET  /products/{slug}                           → SPA route

# REST API (versioned, JSON-only)
GET  /api/v1/registry.json                      → full registry snapshot
GET  /api/v1/products                           → product list
GET  /api/v1/products/{slug}                    → product detail
GET  /api/v1/products/{slug}/versions           → version list
GET  /api/v1/products/{slug}/versions/{ver}     → version detail
POST /api/v1/audit/install                      → installer beacon (opt-in)
GET  /api/v1/orgs/{org}/registry.json           → org-scoped subtree
POST /api/v1/admin/products                     → admin: create product (auth required)
PATCH /api/v1/admin/products/{slug}/versions/{ver}  → admin: update status
DELETE /api/v1/admin/...                        → admin: soft-delete (yank)

# OAuth
GET  /auth/{provider}                           → start OAuth flow (Socialite)
GET  /auth/{provider}/callback                  → callback
POST /auth/logout
POST /api/v1/auth/tokens                        → create personal-access token (admin only)
DELETE /api/v1/auth/tokens/{id}                 → revoke

# WebAuthn (hardware keys for admin sign-in)
POST /webauthn/register                         → enrol a key
POST /webauthn/verify                           → step-up auth for sensitive ops
```

#### UX requirements

- **Mil-grade defaults visible**: every admin action shows
  signing-status, audit-log entry id, and the IP it'll be performed
  from BEFORE the user clicks confirm.
- **Step-up auth** (WebAuthn) gates: yanking a release, deleting an
  org, rotating a token-secret, exporting an audit log.
- **Diff view** before any registry edit: show what the resulting
  `registry.json` will look like.
- **Org switcher** in the navbar: for users that manage multiple
  tenants.
- **Common-user mode**: a public read-only landing that lists all
  current products + their install one-liners. Same look-and-feel
  as the admin.
- **i18n-ready**: every UI string flows through Laravel's
  translation files; English ships at v1, others follow community.
- **A11y**: WCAG 2.2 AA. Every Inertia page tested with axe-core.

Repo: <https://github.com/simtabi/get-installer-admin> (to be created).
Container image: built from `Dockerfile.api` in this repo (the API
container image is generated here so the admin doesn't need to know
about infrastructure).

### Phase N: REST-API client in the installer

Once Phase M is live, this installer should also be able to **read its
registry from the API** (Phase C already drafted; expand here):

- [ ] `Registry.from_url("https://get.simtabi.com/api/v1/registry.json")`
      works identically to `Registry.load(path)`.
- [ ] Optional `Authorization: Bearer <GET_INSTALLER_TOKEN>` for
      private / org-scoped views.
- [ ] Caches the response at `$XDG_CACHE_HOME/get-installer/`.
- [ ] Falls back to a bundled `registry.json` when the API is
      unreachable (clearly warned).

### Phase P: Military-grade security baseline

Goes beyond standard hygiene. The bar most enterprises don't reach.
Each item is **independently shippable**: turn each on with a flag /
config knob so the common-user UX stays simple and the gov / defence /
finance / healthcare customer flips them on.

#### Supply chain

- [ ] **Reproducible bundle**: `scripts/bundle.py` produces
      byte-identical output when fed the same source. The build
      timestamp lives in a side-car (`installer.py.buildinfo.json`),
      not in the bundle body. CI gate compares two consecutive builds
      and fails if they diverge.
- [ ] **SLSA Level 3 provenance**: GitHub Actions release workflow
      attaches a [`slsa-github-generator`](https://github.com/slsa-framework/slsa-github-generator)
      attestation to every release artefact.
- [ ] **SBOM**: `scripts/sbom.py` emits a CycloneDX 1.5 SBOM listing
      every transitive dependency (currently zero, but ship the
      manifest anyway). CI uploads it as a release asset.
- [ ] **Sigstore signing**: every release artefact is signed via
      `cosign sign-blob --keyless` using the GitHub-issued OIDC
      identity. Verification via `cosign verify-blob`.
- [ ] **Multi-signer**: alongside sigstore, accept a per-org PGP key
      pinned in the registry. The installer can require BOTH
      signatures via `verification.require_both = true`.
- [ ] **Pinned base images**: Dockerfile `FROM ubuntu:26.04@sha256:...`
      not `ubuntu:26.04`. Renovate / Dependabot updates the SHA.

#### Runtime hardening

- [ ] **FIPS-compliant crypto** when available: detect a FIPS-mode
      OpenSSL (`hashlib._hashopenssl`) and prefer it; refuse
      non-FIPS hashes when `--fips-mode` is set.
- [ ] **Air-gap install support**: a single tarball
      (`get-installer-airgap-<version>.tar.gz`) contains everything:
      bundle, registry, signatures, the offline-build of any optional
      tooling. `get-installer install-offline <tarball>` runs without
      network access.
- [ ] **Hardware-key step-up** for the admin UI (Phase M): every
      destructive action (yank, delete org, rotate secret, export
      audit log) requires a WebAuthn assertion.
- [ ] **Hash-chained audit log**: each audit row references the
      sha256 of the previous row. Tampering is detectable. Export
      includes a checkpoint hash signed by the server.
- [ ] **mTLS for admin → API**: the admin sidecar authenticates with
      a per-instance client cert issued at provision time.
      Documented but optional.
- [ ] **Capability tokens (Macaroons)**: scoped, attenuable, offline-
      verifiable tokens. The token a CI pipeline holds can ONLY trigger
      product updates for a single product, not yank releases, not
      change org membership, not read audit logs.

#### Threat model docs

- [ ] **`docs/threat-model.md`**: STRIDE per component, mitigations
      cited per line. Updated when any phase ships.
- [ ] **`docs/incident-response.md`**: pre-written runbook: "what to
      do when an `installer.py` SHA we published is reported tampered."
- [ ] **`docs/compliance.md`**: maps our controls to SOC 2 / ISO 27001 /
      NIST SP 800-218 (SSDF) controls. Useful when a customer asks for
      a controls matrix.

#### Common-user defaults

Mil-grade is configurable, NOT mandatory. Defaults stay friendly:

- Signing OFF unless customer flips it on.
- Air-gap install needs an explicit `--air-gap` flag.
- FIPS mode needs `--fips-mode`.
- WebAuthn step-up needs `auth.require_webauthn_for: [...]` in the
  registry.

### Phase Q: Expanded ecosystem support

The installer's stated target was macOS, Linux, Windows. Real-world
developers run on more than three OSes. Each gets a per-platform
support entry in the registry's `supported_platforms` list + a
documented launcher path:

| Ecosystem | Launcher path | Notes |
|---|---|---|
| **macOS** | `install.sh` (POSIX) | ✓ working |
| **Linux** (glibc) | `install.sh` (POSIX) | ✓ working |
| **Linux** (musl / Alpine) | `install.sh` (POSIX) | needs test in CI matrix |
| **Windows** | `install.ps1` | ✓ working; requires admin or Developer Mode for symlinks |
| **WSL** | `install.sh` runs under WSL bash | already works transparently |
| **Git-Bash / Cygwin** (Windows POSIX layers) | `install.sh` | test in CI |
| **ChromeOS** | `install.sh` under Crostini's Debian container | document the `vmc start termina` precondition |
| **Android / Termux** | `install.sh` with `pkg install python git` precondition | document tested combos; no PowerShell |
| **iOS (a-Shell / iSH)** | `install.sh` minimal: only the catalogue mode (no real symlinks to `~/.claude/` since the FS sandbox forbids it) | document degraded mode |
| **FreeBSD / OpenBSD / NetBSD** | `install.sh` | test in CI nightlies |
| **Solaris / illumos** | `install.sh` | best-effort, document caveats |
| **Cloud shells** (Google Cloud Shell, AWS CloudShell, Azure Cloud Shell) | `install.sh` | ephemeral home dirs: note in docs that re-running on every login is the expected pattern |
| **CI environments** (GitHub Actions, GitLab CI, CircleCI, etc.) | `install.sh --yes --no-decisions --dry-run` recipes | give a copy-pasteable matrix per provider |
| **Docker** (containers) | `install.sh` runs in the image build | document a "vendor the installer.py into the image at build time" pattern for air-gapped deploys |

Concretely:

- [ ] Add `supported_ecosystems` to the version-entry schema as a
      richer counterpart to `supported_platforms`. Same shape; broader
      vocabulary.
- [ ] CI matrix: add `macos-14`, `ubuntu-24.04`, `windows-2022`,
      `ubuntu-24.04` with `alpine:edge` container, plus
      `freebsd-14` (via `cross-platform-actions/action` or QEMU).
- [ ] `docs/ecosystems/` with one page per non-mainline target:
      `chromeos.md`, `termux.md`, `ios.md`, `bsd.md`, `cloud-shells.md`,
      `ci.md`, `docker.md`.
- [ ] iOS / catalogue-only mode: when `--mode=catalogue` is set, the
      installer doesn't try to symlink or run pipx: it just prints the
      registry. Useful where the filesystem is sandboxed.

### Phase R: Public landing page + app-store catalogue

The web UI has two distinct surfaces, served by the same Laravel
sibling repo (Phase M):

#### R.1: Public landing page (`https://get.simtabi.com/`)

- [ ] Hero with the one-liner install command per OS, copy-button.
- [ ] **App-store-style catalogue** of all currently published
      products, paginated + filterable by:
      - tag (e.g., `cli`, `dev-tools`, `claude-code`, `enterprise`)
      - supported platform (icons: macOS / Linux / Windows / ChromeOS / Termux / …)
      - license
      - status (`current` shown by default; `deprecated` hidden behind a toggle)
- [ ] **Product detail pages** at `/products/<slug>`:
      - Long description, screenshots, sample install commands
      - Version timeline with status badges (current / deprecated / yanked)
      - Direct download links for each artefact (wheel, bundle, source tarball)
      - Sigstore / SBOM badge when Phase P signing is on
      - One-liner copy buttons per platform
      - Link to the source repo + the docs
- [ ] **Search**: typeahead across product name + tags + summary.
- [ ] **JSON-LD structured data** for SEO; every product is a
      `SoftwareApplication`.
- [ ] **Static-generate when possible**: every public page is rendered
      at build time and served from the CDN; only the catalogue search
      hits the API. Keeps the public side resilient when the API is
      down.
- [ ] **No login required** for the landing/catalogue. Sign-in is
      admin-only.

#### R.2: Admin dashboard (`https://get.simtabi.com/admin/`)

- [ ] OAuth login (GitHub / GitLab / Google / Azure AD via Socialite).
- [ ] WebAuthn step-up for destructive actions.
- [ ] **Product CRUD** with diff preview before save.
- [ ] **Version management**: create / promote `current` → `deprecated`,
      `deprecated` → `yanked`. Each transition writes a hash-chained
      audit row.
- [ ] **Org management** for multi-tenant deployments.
- [ ] **Audit-log viewer** with filter + export to JSONL.
- [ ] **Sigstore signing trigger**: manual or scheduled re-sign.
- [ ] **SBOM viewer**: read-only graph of every published artefact's
      dependencies (CycloneDX import).
- [ ] **Installer beacon dashboard**: counts per product per platform
      per day, opt-in only.

#### R.3: Public API parity

The same data the catalogue / dashboard renders is available under
`/api/v1/...` so SDKs / Terraform / CI scripts can drive everything
the human admin can. The admin UI uses the REST surface internally
(via Inertia + TanStack Query): no special endpoints.

### Phase O: Audit beacons (opt-in telemetry)

For enterprise / government deployments that need install reporting:

- [ ] After a successful install (and after a failure), the installer
      POSTs to `${registry.audit_url}` a minimal beacon:
      `{ product, version, status, host_id (anon), platform, timestamp }`.
- [ ] **Off by default.** Enabled per-registry by setting
      `audit: { url, opt_in_default: false }`. Customers can flip the
      default per-deployment.
- [ ] Anonymous host_id is `sha256(hostname + salt)`; the salt rotates
      per-org so two installs from the same host can be correlated
      within the org but not across orgs.
- [ ] The user can always pass `--no-audit` to refuse beaconing.

## 5: Open issues / known bugs to fix in passing

| # | Where | Issue |
|---|---|---|
| I1 | `src/get_installer/installer.py` | The local import of `python_setup` inside `_phase_validate` should move to top-level. Was deferred to break a potential cycle that no longer exists. |
| I2 | `src/get_installer/verify.py:fetch_https` | The `last_exc` rebind shadows the outer name; mypy doesn't catch it because we cast. Rewrite to use a typed Optional explicitly. |
| I3 | `bootstrap/install.sh` | The `INSTALLER_SHA256` env-var path is documented but tests don't cover it. Add a fixture that fakes a mismatch and confirms the bootstrap exits non-zero. |
| I4 | `src/get_installer/config.py:Registry.list_products` | Sorts versions desc by semver, but pre-release sort ordering hasn't been validated against the real semver-2.0 spec (build metadata not handled). Add a test with a `1.0.0-rc.1` vs `1.0.0` case. |
| I5 | `src/get_installer/installer.py:_phase_post_install` | `subprocess.run(list(step.argv), check=False)`: if a command name has spaces, this fails opaquely. Add a `which` check before exec with a clear error. |
| I6 | `tests/test_installer.py:test_root_refused_without_flag` | Uses `unittest.mock.patch("os.geteuid", create=True)`. On Windows there's no `geteuid`. Add a `pytest.mark.skipif(sys.platform == "win32")`. |
| I7 | `bootstrap/install.ps1` | The trap clause uses `Write-Fail` but if the trap fires inside the `trap` block itself, the script exits with the wrong code. Switch to a `try/finally`. |
| I8 | `src/get_installer/journal.py:JournalEntry` | Not frozen. A misbehaving caller could mutate `description` mid-run. Make it `frozen=True` once we don't need post-init field replacement. |
| I9 | `registry.json` for `claude-configurator` 0.1.0 | `status: deprecated` but the `next_steps` field says "upgrade with pipx upgrade": that only works if 0.1.0 was already installed via pipx. Generalise the message. |
| I10 | All docs | The previous `installer/` path appears in some links / examples that the migration script may not have caught. Grep + sweep. |
| ~~I11~~ | ~~`src/get_installer/installer.py`~~ | ~~Allowed-origins allowlist was dead code.~~ **Resolved 2026-05-14 by Phase C**: `Registry.from_url` is now the live caller of `verify.fetch_https`, and it threads `allowed_origins` through. |
| ~~I12~~ | ~~`bootstrap/install.sh`~~ | ~~`INSTALLER_SHA256` had no test.~~ **Resolved 2026-05-14**: `tests/test_bootstrap_launchers.py` covers match-passes / mismatch-refuses / no-pin-warns paths. |
| ~~I13~~ | ~~All bootstrap path-tests~~ | ~~No end-to-end coverage of `install.sh` / `install.ps1`.~~ **Resolved 2026-05-14**: 5 tests now run `bash -n` + `sh -n` syntax checks, `pwsh` parse check (skipped where unavailable), and an end-to-end flow against a local HTTP server (gated by `INSTALLER_PROTO_OVERRIDE`: test-only). |
| I14 | `bootstrap/install.sh` | The new `INSTALLER_PROTO_OVERRIDE` env var bypasses the HTTPS-only guard for test fixtures. It's loud-warned, but it's still an attack surface if a user sets it by accident. Consider tying the override to a build-time flag (e.g., `-e GET_INSTALLER_TEST_MODE=1`) so prod builds can refuse to honour it at all. |

## 6: Out of scope (explicitly NOT this project)

- **A package manager.** This installs a single package from a known
  source; resolving complex dependency trees is `pip` / `apt` / `brew`'s
  job. We orchestrate, we don't replace.
- **A CI/CD system.** We deploy artefacts; we don't build them.
- **A signing infrastructure.** We verify signatures; signing keys
  live in the customer's HSM / sigstore tenant.
- **A telemetry server.** We emit beacons if the customer runs one;
  we don't ship the server.
- **Running as a long-lived daemon.** Single-shot, transactional, exits.

## 7: Coding conventions (Simtabi-org defaults apply)

See `/Users/imanimanyara/Artisan/projects/opensource/CLAUDE.md` and
`/Users/imanimanyara/.claude/CLAUDE.md` for the full set. Highlights
for agents working in this repo:

- Stdlib only. No runtime deps.
- `mypy --strict` clean. `ruff` clean with the project's selected lints.
- Tests live in `tests/`. Use `tmp_path` for filesystem state.
- Docstrings on every public method.
- No emoji in code, commits, or docs.
- No AI-tells (`leverage`, `powerful`, `robust`, `comprehensive`,
  `seamless`, `essentially`, `note that`, `simply,`) in any
  user-facing prose.
- Commit messages: imperative ≤ 72 chars, body explains *why*.

## 8: Agent-loop instructions

When a coding agent loads this file:

1. **Run the audit checklist at the top FIRST.** Five-line summary
   of findings goes at the top of your first response.
2. **Read every section before writing.**
3. **State the phase you're entering** (e.g., "I'm working on Phase B,
   Bundle script") before any tool calls.
4. **Verify before claiming**: every grep / file count / version
   string must come from a live read or a fresh shell command, not
   from this spec (which decays over time).
5. **Update this file** when you finish a phase. Move the items in §4
   from "[ ]" to "[x]" and add a one-line "✔ <date>" note. Add new
   issues to §5 as you discover them.
6. **Stay scope-tight**. If the user asks for something not in §4 /
   §5, surface it and ask before extending.
7. **No surprise destructive ops.** Per the user's standing
   instructions, no `git push`, `git reset --hard`, force-pushes,
   amends, deletes, etc. without an explicit verb.
8. **Stay a step ahead**: after the user's explicit request, also fix
   any tiny issue you spotted in passing if it's a one-line clean-up
   and germane to the file you touched. Don't expand scope past the
   diff you'd already be making.

## 9: Glossary

| Term | Meaning |
|---|---|
| `curl \| sh` | The technique: piping a remote script into a shell. |
| Bootstrap installer | The script the user runs first; sets up everything else. |
| Distribution channel | The whole system (host + scripts + signatures). |
| Registry | The JSON / API describing every available product + version. |
| Forge | A git host: GitHub, GitLab, Bitbucket, Gitea, etc. |
| Tenancy | The mode controlling who can install what: open / domain-locked / token-locked. |
| Yanked | Status for a release that must never install (security recall). |
| Sigstore | The keyless code-signing system this project plans to use. |
| Bundle | The single-file `installer.py` produced by `scripts/bundle.py`. |

---

## 12: Known design / technical / architectural flaws

Catalogued from the 2026-05-14 systematic review. Ordered by ROI of
fixing. Move items to §5 once they have an explicit owner.

### Architectural

| # | Flaw | Fix |
|---|---|---|
| A-1 | **`registry.json` does dual duty**: it's both the in-repo dev fallback AND the canonical content served at `get.simtabi.com`. Editing one means remembering to edit the other when they diverge. | Move the dev fallback to `registry/samples/dev-registry.json`. The top-level `registry.json` becomes the "what we publish" snapshot, updated only by the release pipeline. |
| A-2 | **No shared contract between client + Phase M admin**. Either side could drift from the schema without the other noticing. | Add `schemas/registry.schema.json` to the get-installer-admin repo via git submodule or vendored copy on each release. Add a CI cross-check that the admin's API responses validate against this schema. |
| A-3 | **No SDK** for the API. Anyone driving the admin programmatically writes raw curl. | After Phase M, generate a Python SDK + a TS SDK from the OpenAPI spec the Laravel admin emits via `dedoc/scramble`. Ship as `get-installer-sdk` (Python) and `@simtabi/get-installer` (npm). |
| A-4 | **`Registry.products: dict[str, dict[str, Any]]`**: `Any` defeats the type system. Product entries are only parsed lazily by `resolve()`. | Parse all products eagerly into typed `Product` / `Version` dataclasses on `load`. Keep the raw dict only for round-trip JSON. |
| A-5 | **Static-CDN + dynamic-API are two stacks** but currently only the static one has a Dockerfile. The Phase M Laravel image will be a separate, larger container. | Ship `Dockerfile.api` here so the deployment story is "two images, both built from this repo's recipes". |
| A-6 | **No client-side cache TTLs** for registry fetches. Every install hits the URL. | Cache the registry at `$XDG_CACHE_HOME/get-installer/registry-<sha>.json` with a 5-minute TTL by default. Refresh on `--refresh`. |
| A-7 | **No standby / mirror story**. If get.simtabi.com goes down, every install fails. | Multi-origin spec: registry can declare `mirrors: ["https://get.example.org", "https://get2.simtabi.com"]`. Client tries each. |

### Technical

| # | Flaw | Fix |
|---|---|---|
| T-1 | **Bundle's stdlib import collection collects everything**, even imports a module only needs internally but exports through `__init__`. Some imports end up unused in the bundle. | Run a dead-import pass after concatenation: import the bundled file in a subprocess, parse its AST, drop top-level imports that aren't referenced. |
| T-2 | **`--allow-deprecated default=True` + `--no-deprecated`** is a confusing dual flag. | Replace with a single tri-state `--deprecated {allow,warn,refuse}` defaulting to `warn`. Same for unsupported / yanked. |
| T-3 | **`_default_registry_path` walks parents** as a last resort: fragile in unusual layouts (notebook-style `cwd`, `pip install --target` setups). | Drop the parent walk. Require either `--registry`, `$GET_INSTALLER_REGISTRY`, or `./registry.json`. Print the searched locations on failure. |
| T-4 | **The bootstrap launchers download from one fixed URL**. No retry across mirrors, no integrity beyond optional SHA pin. | Add the `mirrors` array (paired with A-7) at the bootstrap layer too: `install.sh` tries each in order. |
| T-5 | **No `--json` output mode** anywhere in the CLI. Hard to script around `--list`, `--dry-run` summaries. | Add `--json` to every read-only subcommand. The structured output IS the surface tools depend on. |
| T-6 | **Tests cover Python but not the shell launchers**. `bash -n install.sh` syntax-checks but doesn't prove the flow. | Add an integration test that runs a local HTTP server, points `INSTALLER_BASE_URL` at it, and exercises the bash + PowerShell launchers end-to-end. |
| T-7 | **`__main__.py:_default_registry_path` uses `os.environ.get` then `Path.cwd`**. On Windows, cwd can have unusual case-folding. | Normalise via `Path.resolve()` consistently. |

### Design / UX

| # | Flaw | Fix |
|---|---|---|
| D-1 | **No `uninstall` story for the installer itself**. `pipx uninstall get-installer` works, but `~/.local/share/get-installer/` (cache) lingers. | Add `get-installer uninstall-self --confirm` that prints what would be removed + removes it. Distinct from `uninstall <product>`. |
| D-2 | **Audit beacons (Phase O)** description was OFF-by-default-correct, but the SPEC's prose could lead someone to wire them on. | Tighten the prose. Add a `audit.enabled: false` default in the schema. Document the data-minimisation rules explicitly. |
| D-3 | **No accessibility plan** for the future web UI beyond a one-line WCAG 2.2 AA mention. | Add `docs/accessibility.md` referencing axe-core in CI, screen-reader test cases, keyboard nav requirements. |
| D-4 | **No i18n plan** beyond "i18n-ready". Real i18n needs string-extraction discipline from day 1. | Document the Laravel-side translation flow, the React-side `react-intl` pattern, locale negotiation, RTL support. |
| D-5 | **`--yes` doesn't separate "skip prompts" from "trust everything"**. A `--yes` user still gets the refuse-root guard. Make sure the docs explain this isn't a "yolo" flag. | Rename to `--non-interactive` in v0.3; deprecate `--yes` as an alias. |
| D-6 | **No error-code reference** in `docs/tools/...`. Users see `error: ...` and have to grep. | Add an "Error codes" table + a stable error-code prefix (`E_INSTALL_001`) for each failure path. |

### Security (gaps beyond what §4 Phase H covers)

| # | Flaw | Fix |
|---|---|---|
| S-1 | **No environment variable scrubbing** before `subprocess.run`. A malicious `LD_PRELOAD` survives into the child. | Strip dangerous env vars when invoking installation commands. Allowlist mode. |
| S-2 | **The bootstrap launcher prints debug info on error** that may include the install URL + temp dir paths. Could leak path-disclosure to whoever sees the terminal. | Add a `--quiet-on-error` mode. |
| S-3 | **No rate-limit on the audit beacon**. A misbehaving client could DoS the audit endpoint. | Server-side: per-IP + per-token rate-limit. Documented in Phase M. |
| S-4 | **No tamper-evident logging on the client side**. Server-side has hash-chained audit (Phase P); client logs are flat. | Hash-chain the journal log too. |
| S-5 | **`--allow-root` is a CLI flag**. An attacker who controls the CLI args can pass it. | Add a registry-side `forbid_root` flag that even `--allow-root` cannot override when set. |

## 10: Directory grouping (proposed)

Currently the top-level is flat:

```
get-installer/
├── README.md
├── SPEC.md
├── LICENSE
├── CHANGELOG.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── registry.json
├── .github/
├── bootstrap/
├── deploy/
├── docs/
├── schemas/
├── scripts/
├── src/
└── tests/
```

Proposed regrouping (a v0.2 cleanup: DO NOT do this without an
explicit user OK; it breaks every URL/link/CI reference):

```
get-installer/
├── README.md
├── SPEC.md
├── LICENSE
├── CHANGELOG.md
├── pyproject.toml
├── .gitignore
├── .github/                              CI + dependabot (per-file unchanged)
├── client/                               everything that runs on the user's machine
│   ├── bootstrap/                          install.sh / install.ps1
│   ├── src/get_installer/                  the Python package
│   └── tests/                              the pytest suite
├── server/                               everything that runs at get.simtabi.com
│   ├── Dockerfile                          static-CDN image
│   ├── Dockerfile.api                      (future) API image
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   ├── .env.example
│   └── deploy/                             nginx, supervisor, build-aliases, etc.
├── docs/                                 every doc, grouped by audience
│   ├── users/                              for people running `curl | sh`
│   ├── operators/                          for people running the channel
│   ├── developers/                         for people contributing here
│   └── compliance/                         for procurement / security reviews
├── registry/                             the registry + its schema + samples
│   ├── registry.json
│   ├── schemas/registry.schema.json
│   └── samples/                            example registries (private-org, catalogue, etc.)
└── scripts/                              build + release tooling
    ├── bundle.py
    ├── sbom.py                             (future)
    └── reproducibility-check.sh            (future)
```

**Trade-offs**:

- *Pro*: clear `client/` vs `server/` axis makes the dual-purpose
  nature of the repo legible at a glance.
- *Pro*: `docs/` grouped by audience helps the people doing
  procurement reviews find the compliance doc fast.
- *Con*: every README link, CI workflow path, Dockerfile COPY, and
  user-facing one-liner path breaks.
- *Con*: there is real ambiguity between client+server when both
  share `registry.json` (currently top-level, used by both).

Recommendation: **defer to v0.2.0** unless we're already breaking
URLs. If we go ahead, do it as one focused PR with a migration script
in `scripts/migrate-v0.2.sh`.

## 11: System diagram (text form)

```
                     ┌────────────────────────────────┐
                     │      get.simtabi.com           │
                     │  (CDN: CloudFront / Fastly)    │
                     └────┬────────────────┬──────────┘
                          │                │
              static read │                │ dynamic read/write
                          │                │
                    ┌─────▼─────┐   ┌──────▼────────────┐
                    │  Nginx    │   │  Laravel admin    │
                    │ (Phase K) │   │  (Phase M sibling │
                    │ stdlib    │   │  repo): Inertia  │
                    │ Python    │   │  + React + REST   │
                    │ bundle    │   └──────┬────────────┘
                    └─────┬─────┘          │
                          │                │
                          │           ┌────▼─────────┐
                          │           │ PostgreSQL   │
                          │           │ (Phase K     │
                          │           │  compose)    │
                          │           └──────────────┘
                          │
                          │
            ┌─────────────▼──────────────┐
            │  Bootstrap launchers       │     User's machine
            │  install.sh / install.ps1  ├───▶ python installer.py
            │  download installer.py    │     (the bundle)
            │  + registry.json           │
            └────────────────────────────┘
```

---

*Last updated 2026-05-14 (post-audit: Phase A/B marked complete;
reproducible-bundle, shell-wrapper guard, journal.write_file mode
fixes shipped; new issues I11–I13 logged; Phase Q (broader
ecosystems) + Phase R (landing + catalogue UI) added;
§12 "known flaws" with 25 prioritised items added.)*
