# Registry schema

The installer reads a single `registry.json` (schema v2). It declares
many *products*, each with many *versions*, each marked with a *status*.

The authoritative reference is
[`schemas/registry.schema.json`](../schemas/registry.schema.json). This
page is the prose summary.

## Top-level shape

```json
{
  "schema_version": 2,
  "registry_updated": "YYYY-MM-DD",
  "min_installer_version": "1.0.0",
  "rate_limits":   { ... },
  "access_control": { ... },
  "products": {
    "<product-slug>": { ... }
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Must be `2`. Installer refuses anything else. |
| `registry_updated` | yes | ISO date. Shown for provenance. |
| `min_installer_version` | no | Semver. Installer refuses if its own version is below. Default `1.0.0`. |
| `rate_limits` | no | See [Rate limits](#rate-limits). |
| `access_control` | no | See [Access control](#access-control). |
| `products` | yes | One or more product entries. |

## Products

```json
"claude-configurator": {
  "name": "claude-configurator",
  "summary": "Version your ~/.claude/ via symlinks from a content dir.",
  "homepage": "https://opensource.simtabi.com/products/claude-configurator",
  "default_version": "0.2.0",
  "supported_platforms": ["linux", "darwin", "windows"],
  "versions": {
    "0.2.0": { ... },
    "0.1.0": { ... }
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Display + slug (kebab-case, 2-64 chars). |
| `summary` | yes | One-line description shown by `--list`. |
| `homepage` | no | Product landing URL. |
| `default_version` | yes | Used when user omits `--version`. |
| `supported_platforms` | no | Subset of `linux`, `darwin`, `windows`. Default: all three. |
| `supported_ecosystems` | no | Fine-grained labels (e.g. `linux-glibc`, `linux-musl`, `wsl`, `cloud-shell-aws`). Falls back to `supported_platforms` when empty. |
| `versions` | yes | One or more version entries (keyed by semver). |
| `access` | no | Bearer-token auth + signed-URL expectations (see [Access](#access)). |

## Versions

```json
"0.2.0": {
  "status": "current",
  "released": "2026-05-14",
  "package": "claude-configurator",
  "package_version": "0.2.0",
  "min_python": "3.10",
  "install_method": "auto",
  "required_commands": ["git"],
  "optional_commands": ["pipx", "uv"],
  "post_install": [
    {
      "argv": ["claude-configurator", "--yes", "bootstrap", "--no-git"],
      "if": "run_bootstrap=yes"
    }
  ],
  "content_repo": null,
  "prompts": [
    {
      "key": "run_bootstrap",
      "type": "yes_no",
      "default": true,
      "question": "Run `claude-configurator bootstrap` now?"
    }
  ],
  "next_steps": [
    "claude-configurator status",
    "claude-configurator list"
  ]
}
```

### Required fields

| Field | Notes |
|---|---|
| `status` | One of `current`, `deprecated`, `unsupported`, `yanked`. |
| `package` | PyPI package name. |
| `min_python` | `major.minor` string. Installer refuses lower. |
| `install_method` | `auto` (tries pipx → uv tool → pip --user), or one of those names explicitly. |

### Status semantics

| Status | Behaviour |
|---|---|
| `current` | Installs freely. |
| `deprecated` | Installs with a warning. `--no-deprecated` refuses. |
| `unsupported` | Refuses unless `--allow-unsupported` is passed. |
| `yanked` | Refuses always. Use for security-revoked or broken releases. |

Add a `status_reason` to explain why: surfaced in the warning/error.

### Optional fields

| Field | Notes |
|---|---|
| `package_version` | Defaults to the version key. Useful when registry version ≠ PyPI version. |
| `required_commands` / `optional_commands` | PATH checks before install. Required ⇒ refuse; optional ⇒ warn. |
| `post_install` | List of commands to run after install. Each is `[argv]` or `{argv, if}`. The `if` is `prompt_key=value`; the step is skipped when the prompt answer doesn't match. |
| `content_repo` | Optional git repo to clone into a target path before post-install. `{url, target, ref, optional}`. |
| `prompts` | Interactive questions. Types: `yes_no`, `string`, `choice`. Answers feed `post_install.if`. |
| `next_steps` | Lines printed in the final summary box. |
| `package_sha256` | Reserved for wheel-hash verification (not yet enforced). |

## Rate limits

```json
"rate_limits": {
  "max_retries": 3,
  "retry_backoff_seconds": [1, 2, 5],
  "max_total_seconds": 300,
  "max_bytes_per_download": 10485760,
  "max_concurrent_downloads": 1,
  "request_timeout_seconds": 30
}
```

All fields optional with sensible defaults. The installer applies
these to **any HTTP fetch it does after the bootstrap layer** (e.g.,
optional content downloads, signature lookups). The `install.sh` /
`install.ps1` bootstrap stage uses its own simpler retry policy.

`max_total_seconds` caps the entire install run, not per-request: a
wall-clock deadline. After it expires, the next fetch refuses with a
`SecurityError`.

## Access control

```json
"access_control": {
  "allowed_origins": [
    "https://opensource.simtabi.com/",
    "https://github.com/simtabi/",
    "https://files.pythonhosted.org/",
    "https://pypi.org/"
  ],
  "log_mode": 384,
  "tmp_mode": 384,
  "refuse_symlink_targets_outside": true
}
```

| Field | Effect |
|---|---|
| `allowed_origins` | https:// prefix list. Any fetch the Python core does must start with one of these. Empty list ⇒ no Python-side fetches permitted (the bootstrap is unaffected). |
| `log_mode` | Octal mode (as integer) for the journal log file. `384` = `0o600` = owner only. |
| `tmp_mode` | Same, for downloaded temp files. |
| `refuse_symlink_targets_outside` | When true, follow-symlink operations refuse targets escaping their expected dir. (Currently advisory: used by future content_repo features.) |

## Access

Per-product opt-in block declaring bearer-token auth and / or
pre-signed URL expectations. Public-anonymous products omit it.
Full design + threat model: [`security.md`](security.md).

```json
"private-thing": {
  "name": "private-thing",
  "default_version": "1.0.0",
  "access": {
    "auth": {
      "kind": "bearer",
      "required": true,
      "env_var": "PRIVATE_THING_TOKEN",
      "hint_url": "https://acme.example/get-token"
    },
    "signed": {
      "algorithm": "HMAC-SHA256",
      "query_param": "sig",
      "expires_param": "exp",
      "max_skew_seconds": 60
    },
    "rate_limit_hint": {
      "anonymous_requests_per_hour": 0,
      "authenticated_requests_per_hour": 60
    }
  },
  "versions": { "1.0.0": { /* ... */ } }
}
```

### `access.auth`

| Field | Default | Effect |
|---|---|---|
| `kind` | required | Only `"bearer"` is recognised. |
| `required` | `false` | When true, installer refuses to proceed without a resolved token. |
| `env_var` | `"GET_INSTALLER_TOKEN"` | Env var name checked between the `--auth-token` CLI flag and the global `GET_INSTALLER_TOKEN` fallback. |
| `hint_url` | (none) | URL surfaced in the "no token" error message so the user knows where to fetch one. |

Token resolution order: `--auth-token VALUE` > `$<env_var>` >
`$GET_INSTALLER_TOKEN`. Tokens travel in the `Authorization: Bearer`
header, never in the URL query string.

### `access.signed`

| Field | Default | Effect |
|---|---|---|
| `algorithm` | required | Only `"HMAC-SHA256"` is recognised today. |
| `query_param` | `"sig"` | Name of the HMAC signature query parameter. |
| `expires_param` | `"exp"` | Name of the Unix-seconds expiry query parameter. |
| `max_skew_seconds` | `60` | Tolerance for clock drift. Must be `>= 0`. |

The installer verifies expiry locally; the signature itself is the
server's authorisation and is not re-verified client-side. Refuses
URLs missing either query parameter, with non-numeric `exp`, or
past `exp + max_skew_seconds`.

### `access.rate_limit_hint`

Pure documentation. Real limits are enforced server-side. The client
already honours `429 + Retry-After` via the top-level `rate_limits`
block. Fields:

| Field | Notes |
|---|---|
| `anonymous_requests_per_hour` | Hint to surface in the product's docs / CLI output. `0` means anonymous access is disallowed. |
| `authenticated_requests_per_hour` | Hint for token-holders. |

## Adding a product

1. Add a top-level key under `products`.
2. Provide at least one version entry with `status: current`.
3. Bump `registry_updated`.
4. Run `python -m get_installer --list` to verify it parses.
5. Test installable: `python -m get_installer --product NAME --dry-run --yes`.

## Adding a new version of an existing product

1. Add the version under `products.<name>.versions`.
2. Bump `default_version` to point at it.
3. Move the previous version's `status` from `current` to `deprecated`
   when ready.
4. Add a `status_reason` so users see why.
5. Bump `registry_updated`.

## Yanking a release

1. Change that version's `status` to `yanked`.
2. Add `status_reason` (security advisory link, bug description, etc.).
3. Bump `registry_updated`.

The installer will refuse to install yanked versions even with
`--allow-unsupported`. Users on already-installed yanked versions
should be told to upgrade via the product's own channels.
