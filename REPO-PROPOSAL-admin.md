# Repo proposal — `simtabi/get-installer-admin`

Sibling repo proposal for SPEC §4 Phase M and §4 Phase E. **This is a
proposal document, not an implementation.** The admin app is a
separate-deliverable that needs a dedicated planning conversation
before any code lands.

## Why a separate repo

`get-installer` is a Python tool that runs on the user's machine.
`get-installer-admin` is a web app that serves the registry +
manages multi-tenant install fleets. Different runtime, different
release cadence, different threat model, different audience. They
communicate via the registry-json contract, not in-process code.

## Proposed scope (Phase M)

- Multi-tenant: each tenant has their own registry + product list.
- OAuth: GitHub + GitLab + Microsoft Entra ID at minimum.
- REST API: versioned `/api/v1/`, OpenAPI-spec-first, JSON-only.
- Inertia + React frontend for the admin UI (no Livewire).
- Background workers for periodic checks (PyPI yank watch, etc.).
- Audit log per tenant: every registry edit, who, when, diff.
- Per-tenant domain-locked install (Phase E unblocks here): the
  admin app issues short-lived signed URLs that the installer
  honours via the existing `access_control.allowed_origins`.

## Proposed stack

| Layer | Choice | Rationale |
|---|---|---|
| Framework | Laravel 13 | Most-stable LTS; ecosystem tooling. |
| Auth | Laravel Passport | OAuth2 server; rotate API tokens easily. |
| Frontend | Inertia.js + React 19 | SPA UX, server-rendered routing. |
| Background jobs | Laravel Queue + Redis | Periodic PyPI yank scans, tenant audit-log compaction. |
| DB | PostgreSQL 17 | Native JSON columns for registry payloads. |
| Containerisation | Dockerfile (multi-arch) | Match the get-installer Docker story. |
| Deployment | Self-host or Laravel Forge | Operators pick. |
| CI | GitHub Actions | Same matrix conventions as get-installer + ai-config-kit. |

## Routes (v1 API surface)

```
GET    /api/v1/tenants
GET    /api/v1/tenants/{id}/registry
POST   /api/v1/tenants/{id}/registry
PATCH  /api/v1/tenants/{id}/registry/products/{slug}
GET    /api/v1/tenants/{id}/audit
POST   /api/v1/oauth/token
```

Browser-side: Inertia routes mirror the API.

## Bootstrap checklist (when this kicks off)

- [ ] `gh repo create simtabi/get-installer-admin --public`
- [ ] `composer create-project laravel/laravel . "^13"`
- [ ] Symlink `simtabi/.github` org-default workflows for ci.yml +
      release.yml.
- [ ] Add `composer require laravel/passport inertiajs/inertia-laravel
      tightenco/ziggy`.
- [ ] Frontend scaffolding: `npm install react react-dom @inertiajs/react
      @vitejs/plugin-react`.
- [ ] Define the v1 OpenAPI spec FIRST (under `docs/api/v1.yaml`)
      before wiring controllers.
- [ ] Multi-tenant data model: see `docs/architecture.md` (TBD).
- [ ] OAuth flow design: see `docs/auth.md` (TBD).
- [ ] Threat model: see `SECURITY.md` (TBD).

## What blocks this work

- A confirmed customer / fleet operator who needs multi-tenant. No
  hypothetical builds.
- Decision on hosting: self-host (Forge) or managed (Vapor) or
  customer-installable (Docker Compose).
- Decision on whether to vendor the Phase E (signed-URL) logic into
  the admin app or leave it in the installer.

## What this proposal is NOT

- Not a commitment to build this.
- Not a finalised architecture (every section is open to revision).
- Not on the v0.3 / v0.4 / v0.5 roadmap.

When someone starts work: file an Issue on `simtabi/get-installer`
linking this proposal, hold a planning conversation, then create
the sibling repo from the bootstrap checklist.

_Last update: 2026-05-16. Tracked from RE-AUDIT.md item #23._
