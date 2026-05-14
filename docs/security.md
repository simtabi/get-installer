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

## Reporting a vulnerability

See [`../../SECURITY.md`](../../SECURITY.md). Disclosure goes to
`opensource@simtabi.com`. Don't open a public issue for security
problems.
