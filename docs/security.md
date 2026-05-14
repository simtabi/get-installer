# Security

The installer is **dev-machine code that runs on user devices**. The
threat model focuses on: code-integrity (no surprise binaries),
file-mode hygiene (no world-readable secrets), polite networking (no
DDoSing the registry host), and clean failure (no half-applied state).

## Threats addressed

| Threat | Mitigation |
|---|---|
| MITM swap of `installer.py` | HTTPS-only download in bootstrap. Optional `INSTALLER_SHA256` pin enforces a per-release hash. |
| MITM swap of `registry.json` | Same HTTPS download. Future: signature verification (manifest field reserved). |
| Privilege escalation through installer | Refuse to run as root / Administrator. Override only via explicit `--allow-root` (Unix) / `-AllowRoot` (PowerShell). |
| PATH hijack (e.g., shadowed `pipx`) | `validate` phase warns about world-writable PATH entries. |
| Other users on the machine reading our state | Temp dirs are 0700, journal log is 0600 by default (configurable via `access_control.log_mode`). `O_CREAT|O_EXCL` prevents TOCTOU symlink hijack. |
| Arbitrary URL fetch (a registry that lies about where its files live) | `access_control.allowed_origins` declares an https:// prefix allowlist; Python-side fetches refuse anything else. |
| DDoSing the registry host on retry | Bounded retries with exponential backoff + jitter; respects HTTP 429 Retry-After; wall-clock deadline (`max_total_seconds`) caps the entire run. |
| Mid-install crash leaves half-applied state | Journal records every reversible action; signal handlers (`SIGINT`/`SIGTERM`) and `try/except` at the top level trigger reverse-order rollback. |
| Yanked / security-revoked versions installable | `status: yanked` is refused unconditionally; `unsupported` is refused unless `--allow-unsupported`. |
| Shell-injection via post-install commands | `post_install.argv` is an array passed to `subprocess.run(..., shell=False)`. No shell parsing. |

## Threats NOT addressed (yet)

| Threat | Notes |
|---|---|
| Compromised PyPI package | Out of scope for the installer; PyPI's index sigstore is the upstream protection. `package_sha256` field is reserved for a future wheel-hash check. |
| Compromised registry host with a fresh `INSTALLER_SHA256` | If an attacker controls both `install.sh` and `installer.py`, they can publish a new SHA. The user pins the SHA externally (e.g., from a release page they trust). |
| Build supply-chain attacks on `uv` / `pipx` / `pip` | The installer trusts these tools' integrity. Out of scope. |

## Configuration knobs

All in `registry.json`:

```json
{
  "rate_limits": {
    "max_retries": 3,
    "retry_backoff_seconds": [1, 2, 5],
    "max_total_seconds": 300,
    "max_bytes_per_download": 10485760,
    "max_concurrent_downloads": 1,
    "request_timeout_seconds": 30
  },
  "access_control": {
    "allowed_origins": ["https://opensource.simtabi.com/", "https://github.com/simtabi/"],
    "log_mode": 384,
    "tmp_mode": 384,
    "refuse_symlink_targets_outside": true
  }
}
```

## Refusing on weak environments

The installer refuses (`exit 2`) if:

- Running as root/Administrator without `--allow-root`.
- Python is below the version's `min_python`.
- A `required_commands` entry isn't on PATH.
- The registry's `schema_version` ≠ 2.
- A version's `status` is `yanked`.
- A URL fetch attempt is non-https or not in `allowed_origins`.

It warns (and continues) on:

- World-writable PATH entries.
- Missing `optional_commands`.
- Deprecated version (unless `--no-deprecated`).
- Missing `INSTALLER_SHA256` env var (bootstrap layer).

## Authenticated + signed + rate-limited distribution (Phase L)

Some product channels need access control: private enterprise builds,
preview tracks, paid tiers, or government-domain-locked artefacts.
The installer supports three orthogonal mechanisms that can stack:

1. **Bearer-token auth** for password-protected URLs.
2. **HMAC-SHA256 URL signing** for time-bound, server-issued URLs.
3. **Server-enforced rate limiting** with client-side `Retry-After`
   honour (already shipped).

Each is declared per product (or per version) in `registry.json`
under an `access` block. Products without an `access` block remain
public-anonymous.

### Schema additions

```json
{
  "products": {
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
      "versions": { /* ... */ }
    }
  }
}
```

Field-by-field:

| Field | Required | Behaviour |
|---|---|---|
| `auth.kind` | yes | `bearer` (only kind supported today). Future: `basic`. |
| `auth.required` | yes | If true, installer refuses to proceed without a token. |
| `auth.env_var` | no | Env var the user can set instead of `--auth-token`. Defaults to `GET_INSTALLER_TOKEN`. |
| `auth.hint_url` | no | Surfaced to the user in the "no token" error message. |
| `signed.algorithm` | yes | Only `HMAC-SHA256` recognised. |
| `signed.query_param` | no | Defaults to `sig`. |
| `signed.expires_param` | no | Defaults to `exp` (Unix seconds since epoch). |
| `signed.max_skew_seconds` | no | Tolerance for clock drift. Defaults to 60. |
| `rate_limit_hint.*` | no | Pure documentation. Server enforces real limits. |

### Token resolution order (bearer auth)

1. `--auth-token VALUE` on the CLI.
2. The env var named by `access.auth.env_var` (per-product).
3. `$GET_INSTALLER_TOKEN` (global fallback).
4. Refuse with `SecurityError` if `auth.required=true` and none above
   resolved, surfacing `hint_url` if present.

The token is sent as `Authorization: Bearer <token>` on every fetch
to the product's declared URLs. Never as a query parameter (prevents
token leakage to access logs / referer headers / CI traces).

### HMAC-SHA256 URL signing (client-side verification)

When a product's `registry.json` entry declares `signed`, every URL
the installer fetches for that product is expected to carry
`?<query_param>=<hex-sha>&<expires_param>=<unix-seconds>`. The client:

1. Refuses URLs missing either query parameter.
2. Parses `<expires_param>` and refuses if `now > expires +
   max_skew_seconds`.
3. Does **not** re-verify the HMAC client-side. The signature is
   the server's promise that the URL was authorised; the server is
   the verifier. The client checks expiry only.

This matches the AWS / GCS / Cloudflare R2 pre-signed-URL pattern.
The installer never holds the signing key.

For self-hosters: see
[`cloudflare-tunnel.md`](cloudflare-tunnel.md)
for issuing pre-signed Cloudflare R2 URLs, and
[`vps.md`](vps.md) for the nginx + signing sidecar pattern.

### Rate-limit handling (client side)

Already implemented in `verify.fetch_https`. On HTTP 429:

1. Read `Retry-After` (seconds or HTTP-date).
2. Wait that long (capped at the registry's
   `rate_limits.retry_backoff_seconds` ceiling).
3. Retry up to `rate_limits.max_retries` times.
4. The wall-clock deadline `max_total_seconds` caps the whole run.

Servers should:
- Issue 429 on rate-limit hits (not 403).
- Set `Retry-After` to a real positive integer.
- Distinguish per-token from per-IP limits in their response body
  (the installer surfaces the body in the error message).

### Threat model deltas

| Threat | Mitigation |
|---|---|
| Stolen token replayed by attacker | Tokens travel in the `Authorization` header (not URL); rotate via `auth.hint_url` on revocation. Combine with `signed` to bound the replay window. |
| Pre-signed URL replayed after issuance | `expires_param` caps replay window; `max_skew_seconds` is the only fudge. |
| Server lies about `expires_param` | The installer is the verifier of expiry; the server can't lie unless it controls the user's clock. |
| Token leaked via shell history | Prefer `--auth-token "$(cat ~/.config/get-installer/token)"` or set the env var; never `--auth-token AAA` verbatim. |
| Rate-limit bypass by retrying immediately | Client refuses to retry faster than `Retry-After`. |

### What's intentionally out of scope

- **Mutual TLS / client certificates**: defer to Phase E (multi-tenant).
- **Basic auth (challenge/response)**: bearer is the documented path; basic only as a future opt-in.
- **OAuth flows**: out of scope for a one-shot installer.
- **Token refresh**: the installer is a one-shot tool; users are expected to feed it a current token.

## Reporting a vulnerability

See [`../SECURITY.md`](../SECURITY.md). Disclosure goes to
`opensource@simtabi.com`. Don't open a public issue for security
problems.
