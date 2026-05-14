"""Security primitives: SHA256, HTTPS-only downloads, refuse-root, PATH guard.

Anything that touches the network or filesystem with elevated risk lives
here so the threat-model audit has one place to look.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import random
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class SecurityError(Exception):
    """Raised when a security pre-flight check fails."""


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
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(req, timeout=timeout) as resp:
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
