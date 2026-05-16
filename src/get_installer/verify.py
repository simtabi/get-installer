"""Security primitives: SHA256, HTTPS-only downloads, refuse-root, PATH guard.

Anything that touches the network or filesystem with elevated risk lives
here so the threat-model audit has one place to look.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import random
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class SecurityError(Exception):
    """Raised when a security pre-flight check fails."""


def _hardened_ssl_context() -> ssl.SSLContext:
    """SSL context with TLS 1.2 minimum + system CA bundle.

    Modern Python defaults to TLS 1.2+ already, but pinning it
    explicitly removes a downgrade-attack surface if some downstream
    flips the default. The system CA bundle is the default
    ``create_default_context()`` source.
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def sign_bundle_with_sigstore(
    bundle_path: Path,
    *,
    dry_run: bool = True,
) -> Path:
    """Sign ``bundle_path`` with sigstore (SCAFFOLD — Phase F).

    Wired today as a clean opt-in surface; full signing is pending
    the key-management ADR. Install with::

        pip install 'get-installer[sigstore]'

    @param bundle_path  the installer.py to sign.
    @param dry_run      no actual signing yet.
    @return  the .sig path that would be written.
    @raises SecurityError when sigstore is not installed.
    @raises NotImplementedError when called with dry_run=False —
        we'd rather fail loudly than silently produce a no-op.
    """
    try:
        import sigstore  # type: ignore[import-not-found]  # noqa: F401  # optional [sigstore] extra
    except ImportError as e:
        raise SecurityError(
            "Sigstore signing requires the sigstore package. "
            "Install via: pip install 'get-installer[sigstore]'"
        ) from e
    sig_path = bundle_path.with_suffix(bundle_path.suffix + ".sigstore")
    if dry_run:
        return sig_path
    raise NotImplementedError(
        "Sigstore signing is pending the key-management ADR. The "
        "scaffold + extras install are ready; the actual sign() call + "
        "verification command land in a follow-up release. See "
        "SPEC §4 Phase F for the design questions still open."
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_https(
    url: str,
    dest: Path,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    timeout: float = 30.0,
    max_retries: int = 0,
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0, 5.0),
    deadline_seconds: float | None = None,
    allowed_origins: tuple[str, ...] = (),
    file_mode: int = 0o600,
    extra_headers: dict[str, str] | None = None,
) -> int:
    """Download ``url`` to ``dest`` over HTTPS. Returns bytes written.

    Hardening:
    - Refuses non-https URLs.
    - Refuses URLs whose prefix isn't in ``allowed_origins`` (when set).
    - Caps size at ``max_bytes`` (mid-stream abort, not just trust
      Content-Length).
    - Caps total wall-clock at ``deadline_seconds`` across all retries.
    - Atomic write via sibling temp file; final mode set to ``file_mode``.
    - Exponential backoff with jitter; respects HTTP 429 Retry-After.

    ``extra_headers`` are added to the request alongside the default
    ``User-Agent``. Use this to pass ``Authorization: Bearer …`` for
    authenticated registries. The values are sent verbatim: caller is
    responsible for not putting newlines in them (header injection).
    """
    if not url.startswith("https://"):
        raise SecurityError(f"refusing non-https URL: {url}")
    if allowed_origins and not any(url.startswith(prefix) for prefix in allowed_origins):
        raise SecurityError(
            f"URL not in allowed_origins: {url}\n"
            f"  allowed: {', '.join(allowed_origins)}"
        )

    deadline = (time.monotonic() + deadline_seconds) if deadline_seconds else None

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise SecurityError(
                f"deadline exceeded ({deadline_seconds}s total) before {url}"
            )

        tmp = dest.with_name(dest.name + ".dl-tmp")
        # O_EXCL prevents a TOCTOU symlink replacement attack
        try:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
        except FileExistsError:
            tmp.unlink()
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)

        total = 0
        headers: dict[str, str] = {"User-Agent": "get-installer/1.0"}
        if extra_headers:
            for k, v in extra_headers.items():
                # Refuse header values containing newlines (HTTP header injection)
                if "\r" in v or "\n" in v:
                    raise SecurityError(
                        f"refusing header value with CR/LF for {k!r}"
                    )
                headers[k] = v
        req = urllib.request.Request(url, headers=headers)
        try:
            ctx = _hardened_ssl_context()
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(
                req, timeout=timeout, context=ctx,
            ) as resp:
                status = getattr(resp, "status", None)
                if status is not None and not (200 <= int(status) < 300):
                    if int(status) == 429 and attempt < max_retries:
                        retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                        last_exc = SecurityError(
                            f"rate-limited (429) on {url}; backing off"
                        )
                        _sleep_with_deadline(
                            max(retry_after, _backoff(retry_backoff_seconds, attempt)),
                            deadline,
                        )
                        tmp.unlink()
                        continue
                    raise SecurityError(f"non-2xx response: {status} for {url}")
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise SecurityError(
                            f"download exceeds {max_bytes} bytes for {url}"
                        )
                    f.write(chunk)
        except urllib.error.URLError as e:
            with contextlib.suppress(OSError):
                tmp.unlink()
            last_exc = SecurityError(f"download failed for {url}: {e}")
            if attempt < max_retries:
                _sleep_with_deadline(_backoff(retry_backoff_seconds, attempt), deadline)
                continue
            raise last_exc from e
        except Exception:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

        # Atomic rename (preserves the secure mode set at open)
        os.replace(str(tmp), str(dest))
        with contextlib.suppress(OSError):
            os.chmod(str(dest), file_mode)
        return total

    raise last_exc or SecurityError(f"exhausted retries for {url}")


def _backoff(schedule: tuple[float, ...], attempt: int) -> float:
    """Return the sleep for ``attempt`` using ``schedule`` with jitter."""
    if not schedule:
        return 1.0
    base = schedule[min(attempt, len(schedule) - 1)]
    jitter = random.uniform(0, base * 0.25)
    return base + jitter


def _sleep_with_deadline(seconds: float, deadline: float | None) -> None:
    if deadline is None:
        time.sleep(seconds)
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    time.sleep(min(seconds, remaining))


def verify_sha256(path: Path, expected_hex: str) -> None:
    actual = sha256_of(path)
    if actual != expected_hex:
        raise SecurityError(
            f"sha256 mismatch for {path}: expected {expected_hex}, got {actual}"
        )


def refuse_root(allow: bool = False) -> None:
    """Block running as root by default."""
    if allow:
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise SecurityError(
            "refusing to run as root. If you really mean it, pass --allow-root.\n"
            "Most installs should run as the target user: root installs leave "
            "files owned by root and break later runs."
        )


def check_path_injection() -> list[str]:
    """Return a list of warnings for risky PATH entries.

    World-writable entries in PATH let a local attacker shadow `python`, `pipx`,
    `git`, etc. with a malicious binary. We warn but don't refuse: common
    enough on dev machines that hard-failing would be annoying.
    """
    warnings: list[str] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            st = os.stat(entry)
        except OSError:
            continue
        if st.st_mode & stat.S_IWOTH:
            warnings.append(f"world-writable PATH entry: {entry}")
    return warnings


def python_version_at_least(major: int, minor: int) -> bool:
    return sys.version_info[:2] >= (major, minor)


# ---- Phase L: signed-URL expiry check + bearer-token preflight -----------

DEFAULT_SIGNATURE_QUERY_PARAM = "sig"
DEFAULT_EXPIRES_QUERY_PARAM = "exp"
DEFAULT_MAX_SKEW_SECONDS = 60


def check_signed_url(
    url: str,
    *,
    query_param: str = DEFAULT_SIGNATURE_QUERY_PARAM,
    expires_param: str = DEFAULT_EXPIRES_QUERY_PARAM,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
    now: float | None = None,
) -> None:
    """Validate a pre-signed URL's expiry against the local clock.

    The signature itself is the server's authorisation token; the
    installer doesn't hold the signing key and can't re-verify the
    HMAC. What it CAN verify is that the URL still has time on it,
    which gates the most common replay window.

    Raises ``SecurityError`` if:

    - The URL doesn't carry the configured signature query param.
    - The URL doesn't carry the expires param, or it's non-numeric.
    - ``now > expires + max_skew_seconds``.

    Args:
        url: the pre-signed URL to check.
        query_param: name of the signature query parameter.
        expires_param: name of the Unix-seconds expiry parameter.
        max_skew_seconds: clock-drift tolerance in seconds.
        now: override for ``time.time()`` (test injection).
    """
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)

    sig_vals = qs.get(query_param)
    if not sig_vals or not sig_vals[0]:
        raise SecurityError(
            f"signed URL missing {query_param!r} parameter: {url}"
        )
    exp_vals = qs.get(expires_param)
    if not exp_vals or not exp_vals[0]:
        raise SecurityError(
            f"signed URL missing {expires_param!r} parameter: {url}"
        )

    try:
        expires_at = int(exp_vals[0])
    except ValueError as e:
        raise SecurityError(
            f"signed URL {expires_param!r} not an integer: {exp_vals[0]!r}"
        ) from e

    current = now if now is not None else time.time()
    if current > expires_at + max_skew_seconds:
        delta = int(current - expires_at)
        raise SecurityError(
            f"signed URL expired ({delta}s ago, "
            f"skew tolerance {max_skew_seconds}s): {url}"
        )


def resolve_auth_token(
    cli_token: str | None,
    *,
    product_env_var: str | None = None,
    global_env_var: str = "GET_INSTALLER_TOKEN",
) -> str | None:
    """Resolve a bearer token from CLI > product env > global env.

    Returns ``None`` if no token resolves. Callers decide whether
    ``None`` is fatal (e.g., when the product's
    ``access.auth.required`` is true).
    """
    if cli_token:
        return cli_token
    if product_env_var:
        val = os.environ.get(product_env_var)
        if val:
            return val
    return os.environ.get(global_env_var)


def require_auth_token(
    token: str | None,
    *,
    product_name: str,
    env_var: str,
    hint_url: str | None = None,
) -> str:
    """Raise ``SecurityError`` with a helpful message when token missing.

    Used when a product's registry entry declares
    ``access.auth.required = true``. The message surfaces both the
    env-var name and the optional hint URL so the user can self-help
    without diving into the registry.
    """
    if token:
        return token
    parts = [
        f"{product_name} requires an auth token but none was provided.",
        f"Pass --auth-token VALUE or set the {env_var} env var.",
    ]
    if hint_url:
        parts.append(f"Get a token from {hint_url}.")
    raise SecurityError(" ".join(parts))
