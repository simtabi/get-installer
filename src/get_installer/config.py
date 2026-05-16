"""Load + validate a Simtabi installer registry (schema_version 2).

A registry contains many *products*. Each product has many *versions*,
each with a ``status`` (current / deprecated / unsupported / yanked)
plus the per-version install config (package name, install method,
prompts, post-install commands, etc.).

The installer takes a registry + a ``(product, version)`` selector and
resolves to a single ``InstallConfig`` it knows how to run.

Stdlib-only: no jsonschema dependency. We hand-validate the shape we
consume and rely on the JSON schema (see ``schemas/``) as the
authoritative reference for the format.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import verify


class ConfigError(Exception):
    """Raised when the registry is missing, malformed, or invalid."""


class ResolutionError(Exception):
    """Raised when (product, version) doesn't resolve to an installable entry."""


SUPPORTED_REGISTRY_SCHEMA = 2
SUPPORTED_STATUSES = ("current", "deprecated", "unsupported", "yanked")
SUPPORTED_PLATFORMS = ("linux", "darwin", "windows")
SUPPORTED_INSTALL_METHODS = ("auto", "pipx", "uv-tool", "pip-user")

# Tools that, when used as the first argv with `-c`, turn the argv array
# into a shell string and undo the ``shell=False`` contract.
_SHELL_WRAPPERS = (
    r"(?:.*/)?(?:b?a?sh|dash|zsh|ksh|fish|csh|tcsh|"
    r"powershell|pwsh|cmd|cmd\.exe|"
    r"python|python\d|python\d\.\d+|"
    r"node|deno|ruby|perl|php)"
)
_SHELL_WRAPPER_RE = re.compile(_SHELL_WRAPPERS)


# ---------------------------------------------------------------------------
# Frozen value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Prompt:
    key: str
    type: str
    question: str
    default: Any = None
    choices: tuple[str, ...] = ()
    secret: bool = False


@dataclass(frozen=True)
class RateLimits:
    """Bounds the installer enforces on network + retry behaviour.

    Protects upstream servers (don't hammer the registry host) and the
    user (cap the time/bandwidth the installer can consume). Configured
    in the registry under top-level ``rate_limits``.
    """

    max_retries: int = 3
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0, 5.0)
    max_total_seconds: float = 300.0
    max_bytes_per_download: int = 10 * 1024 * 1024  # 10 MiB
    max_concurrent_downloads: int = 1
    request_timeout_seconds: float = 30.0


@dataclass(frozen=True)
class AccessControl:
    """Origin allowlist + filesystem permissions for installer-created paths.

    ``allowed_origins`` is an https:// prefix list. The installer refuses
    to fetch from a URL whose prefix isn't on this list. Default: empty
    (no fetches allowed beyond what the bootstrap already did).
    """

    allowed_origins: tuple[str, ...] = ()
    log_mode: int = 0o600
    tmp_mode: int = 0o600
    refuse_symlink_targets_outside: bool = True


@dataclass(frozen=True)
class PostInstallStep:
    """A single post-install command, optionally gated on a prompt answer."""

    argv: tuple[str, ...]
    if_expr: str | None = None  # e.g. "run_bootstrap=yes"


@dataclass(frozen=True)
class ContentRepo:
    url: str
    target: str
    ref: str = "main"
    optional: bool = True


@dataclass(frozen=True)
class AuthAccess:
    """Per-product bearer-token auth declaration (Phase L).

    Surfaces from ``products.<name>.access.auth`` in registry.json.
    """

    kind: str = "bearer"          # only "bearer" is honoured today
    required: bool = False
    env_var: str = "GET_INSTALLER_TOKEN"
    hint_url: str | None = None


@dataclass(frozen=True)
class SignedAccess:
    """Per-product signed-URL declaration (Phase L).

    Surfaces from ``products.<name>.access.signed`` in registry.json.
    The installer verifies expiry locally; the signature itself is
    server-issued and not re-verified client-side.
    """

    algorithm: str = "HMAC-SHA256"   # only HMAC-SHA256 is recognised
    query_param: str = "sig"
    expires_param: str = "exp"
    max_skew_seconds: int = 60


@dataclass(frozen=True)
class ProductAccess:
    """Composed access declaration for a single product.

    ``auth`` is None when the product is public-anonymous (no token
    needed). ``signed`` is None when URLs aren't pre-signed.
    """

    auth: AuthAccess | None = None
    signed: SignedAccess | None = None


@dataclass(frozen=True)
class InstallConfig:
    """Resolved single-version config: what the Installer consumes."""

    product: str
    version: str
    status: str
    status_reason: str
    released: str
    package: str
    package_version: str  # PyPI version pin (may equal `version`)
    min_python: tuple[int, int]
    install_method: str
    required_commands: tuple[str, ...] = ()
    optional_commands: tuple[str, ...] = ()
    post_install: tuple[PostInstallStep, ...] = ()
    content_repo: ContentRepo | None = None
    prompts: tuple[Prompt, ...] = ()
    next_steps: tuple[str, ...] = ()
    package_sha256: str | None = None
    supported_platforms: tuple[str, ...] = ()
    homepage: str = ""
    summary: str = ""
    access: ProductAccess = field(default_factory=ProductAccess)

    @property
    def is_current(self) -> bool:
        return self.status == "current"

    @property
    def is_deprecated(self) -> bool:
        return self.status == "deprecated"

    @property
    def is_unsupported(self) -> bool:
        return self.status == "unsupported"

    @property
    def is_yanked(self) -> bool:
        return self.status == "yanked"


@dataclass(frozen=True)
class ProductSummary:
    """Used by ``Registry.list_products`` for the CLI ``--list`` output."""

    name: str
    summary: str
    default_version: str
    available_versions: tuple[str, ...]
    supported_platforms: tuple[str, ...]


# ---------------------------------------------------------------------------
# Registry: many products, many versions, with resolution logic
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Registry:
    schema_version: int
    registry_updated: str
    min_installer_version: str
    products: dict[str, dict[str, Any]] = field(default_factory=dict)
    rate_limits: RateLimits = field(default_factory=RateLimits)
    access_control: AccessControl = field(default_factory=AccessControl)
    source_path: Path | None = field(default=None, compare=False)

    @classmethod
    def load(cls, path: Path | str) -> Registry:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise ConfigError(f"registry not found: {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"invalid JSON in {p}: line {e.lineno}: {e.msg}") from e
        return cls.from_dict(data, source_path=p)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        auth_token: str | None = None,
        fallback_path: Path | str | None = None,
        cache_dir: Path | str | None = None,
        cache_max_age_seconds: float = 300.0,
        allowed_origins: tuple[str, ...] = (),
        timeout: float = 30.0,
    ) -> Registry:
        """Load the registry from an HTTPS URL with optional auth + caching.

        Behaviour:
          1. If a fresh cached copy exists (< ``cache_max_age_seconds``
             old), use it. Network only hit on miss / expiry.
          2. On cache miss, fetch via ``verify.fetch_https`` (which
             enforces ``allowed_origins`` if set, applies the size cap,
             and writes 0600 mode).
          3. On any fetch failure, fall back to ``fallback_path`` if
             one was passed. If that's also unavailable, raise.

        ``auth_token`` is sent as ``Authorization: Bearer <token>``. The
        token can also come from the ``GET_INSTALLER_TOKEN`` env var
        when not passed explicitly: that lookup happens in the CLI, not
        here, so library users have to be explicit.

        The cache key is sha256 of the URL: so different URLs cache
        independently, and the same URL hits the same file.
        """
        import time as _time

        cache_path: Path | None = None
        if cache_dir is not None:
            import hashlib as _hashlib

            cd = Path(cache_dir).expanduser()
            cd.mkdir(parents=True, exist_ok=True, mode=0o700)
            key = _hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            cache_path = cd / f"registry-{key}.json"
            if cache_path.is_file():
                # Clamp age to 0: on Windows (and some FUSE mounts)
                # st_mtime can land slightly in the future after a rename
                # because of filesystem-time vs wall-clock precision skew,
                # producing a negative age. A just-written cache is fresh,
                # not stale; treat negatives as 0. `cache_max_age_seconds=0`
                # still correctly bypasses (0 < 0 is False).
                age = max(0.0, _time.time() - cache_path.stat().st_mtime)
                if age < cache_max_age_seconds:
                    try:
                        data = json.loads(cache_path.read_text(encoding="utf-8"))
                        return cls.from_dict(data, source_path=cache_path)
                    except json.JSONDecodeError:
                        # Corrupt cache: fall through to refetch
                        cache_path.unlink()

        # Network fetch via the hardened helper
        import tempfile as _tempfile

        with _tempfile.NamedTemporaryFile(
            prefix="registry-",
            suffix=".json.tmp",
            delete=False,
            dir=str(cache_path.parent) if cache_path is not None else None,
        ) as tf:
            tmp = Path(tf.name)
        # NamedTemporaryFile opens the file; close immediately so
        # ``fetch_https`` can use ``O_CREAT|O_EXCL`` semantics on a
        # fresh path.
        import contextlib as _ctx
        with _ctx.suppress(OSError):
            tmp.unlink()

        headers_dict: dict[str, str] = {}
        if auth_token:
            headers_dict["Authorization"] = f"Bearer {auth_token}"

        try:
            verify.fetch_https(
                url,
                tmp,
                max_bytes=10 * 1024 * 1024,
                timeout=timeout,
                allowed_origins=allowed_origins,
                file_mode=0o600,
                extra_headers=headers_dict,
            )
        except verify.SecurityError as e:
            if fallback_path is not None:
                fb = Path(fallback_path).expanduser().resolve()
                if fb.is_file():
                    import sys as _sys
                    _sys.stderr.write(
                        f"warning: registry fetch failed for {url}: {e}; "
                        f"falling back to {fb}\n"
                    )
                    return cls.load(fb)
            raise ConfigError(f"registry fetch failed: {e}") from e

        try:
            data = json.loads(tmp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"invalid JSON returned from {url}: line {e.lineno}: {e.msg}"
            ) from e
        finally:
            # If we have a cache_path, atomically rename tmp -> cache_path
            # so the next call hits the cache. Otherwise drop the tmp.
            import contextlib as _ctx2
            if cache_path is not None:
                try:
                    tmp.replace(cache_path)
                except OSError:
                    # Best effort: don't fail the load over cache write
                    with _ctx2.suppress(OSError):
                        tmp.unlink()
            else:
                with _ctx2.suppress(OSError):
                    tmp.unlink()

        return cls.from_dict(
            data, source_path=cache_path if cache_path else None
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> Registry:
        _require(data, "schema_version", int)
        if data["schema_version"] != SUPPORTED_REGISTRY_SCHEMA:
            raise ConfigError(
                f"unsupported schema_version {data['schema_version']}; this installer "
                f"reads version {SUPPORTED_REGISTRY_SCHEMA}"
            )
        registry_updated = _require(data, "registry_updated", str)
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", registry_updated):
            raise ConfigError(f"invalid registry_updated: {registry_updated!r} (YYYY-MM-DD)")

        min_installer = data.get("min_installer_version", "1.0.0")
        if not isinstance(min_installer, str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+", min_installer
        ):
            raise ConfigError(f"invalid min_installer_version: {min_installer!r}")

        products = _require(data, "products", dict)
        if not products:
            raise ConfigError("registry has zero products")
        for name in products:
            if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", name):
                raise ConfigError(f"invalid product slug: {name!r}")

        # Rate limits: all fields optional
        rl_raw = data.get("rate_limits") or {}
        if not isinstance(rl_raw, dict):
            raise ConfigError("rate_limits must be an object")
        rate_limits = RateLimits(
            max_retries=int(rl_raw.get("max_retries", 3)),
            retry_backoff_seconds=tuple(
                float(x) for x in rl_raw.get("retry_backoff_seconds", [1.0, 2.0, 5.0])
            ),
            max_total_seconds=float(rl_raw.get("max_total_seconds", 300.0)),
            max_bytes_per_download=int(rl_raw.get("max_bytes_per_download", 10 * 1024 * 1024)),
            max_concurrent_downloads=int(rl_raw.get("max_concurrent_downloads", 1)),
            request_timeout_seconds=float(rl_raw.get("request_timeout_seconds", 30.0)),
        )
        if rate_limits.max_retries < 0:
            raise ConfigError("rate_limits.max_retries must be >= 0")
        if rate_limits.max_total_seconds <= 0:
            raise ConfigError("rate_limits.max_total_seconds must be > 0")

        # Access control
        ac_raw = data.get("access_control") or {}
        if not isinstance(ac_raw, dict):
            raise ConfigError("access_control must be an object")
        origins = tuple(_as_list(ac_raw.get("allowed_origins", []), str))
        for u in origins:
            if not u.startswith("https://"):
                raise ConfigError(
                    f"access_control.allowed_origins entry must use https://: {u}"
                )
        access_control = AccessControl(
            allowed_origins=origins,
            log_mode=int(ac_raw.get("log_mode", 0o600)),
            tmp_mode=int(ac_raw.get("tmp_mode", 0o600)),
            refuse_symlink_targets_outside=bool(
                ac_raw.get("refuse_symlink_targets_outside", True)
            ),
        )
        if not (0 <= access_control.log_mode <= 0o777):
            raise ConfigError("access_control.log_mode must be 0..0o777")
        if not (0 <= access_control.tmp_mode <= 0o777):
            raise ConfigError("access_control.tmp_mode must be 0..0o777")

        return cls(
            schema_version=SUPPORTED_REGISTRY_SCHEMA,
            registry_updated=registry_updated,
            min_installer_version=min_installer,
            products=products,
            rate_limits=rate_limits,
            access_control=access_control,
            source_path=source_path,
        )

    # ---- listing ----------------------------------------------------

    def list_products(self) -> list[ProductSummary]:
        out: list[ProductSummary] = []
        for name, prod in sorted(self.products.items()):
            versions = tuple(sorted(prod.get("versions", {}).keys(), key=_semver_key, reverse=True))
            out.append(ProductSummary(
                name=name,
                summary=str(prod.get("summary", "")),
                default_version=str(prod.get("default_version", "")),
                available_versions=versions,
                supported_platforms=tuple(prod.get("supported_platforms", SUPPORTED_PLATFORMS)),
            ))
        return out

    # ---- resolution -------------------------------------------------

    def resolve(
        self,
        product: str,
        version: str | None = None,
        *,
        platform: str | None = None,
        allow_deprecated: bool = True,
        allow_unsupported: bool = False,
    ) -> InstallConfig:
        """Resolve (product, version) to an InstallConfig. Validates status + platform."""
        if product not in self.products:
            available = ", ".join(sorted(self.products.keys()))
            raise ResolutionError(
                f"unknown product {product!r}. Available: {available}"
            )
        prod = self.products[product]
        prod_summary = str(prod.get("summary", ""))
        prod_homepage = str(prod.get("homepage", ""))
        prod_platforms = tuple(prod.get("supported_platforms", SUPPORTED_PLATFORMS))
        versions = prod.get("versions", {})
        if not isinstance(versions, dict) or not versions:
            raise ResolutionError(f"product {product!r} has no versions")

        # Resolve version
        if version is None or version in ("latest", "default"):
            version = str(prod.get("default_version", ""))
            if not version:
                raise ResolutionError(f"product {product!r} has no default_version")
        if version not in versions:
            available = ", ".join(sorted(versions.keys(), key=_semver_key, reverse=True))
            raise ResolutionError(
                f"unknown version {version!r} for {product!r}. Available: {available}"
            )

        # Platform check
        if platform is not None and platform not in prod_platforms:
            raise ResolutionError(
                f"{product!r} does not support platform {platform!r}. "
                f"Supported: {', '.join(prod_platforms)}"
            )

        ver_data = versions[version]
        if not isinstance(ver_data, dict):
            raise ConfigError(f"{product}@{version}: version entry must be an object")

        return _build_install_config(
            product=product,
            version=version,
            ver_data=ver_data,
            prod_summary=prod_summary,
            prod_homepage=prod_homepage,
            prod_platforms=prod_platforms,
            allow_deprecated=allow_deprecated,
            allow_unsupported=allow_unsupported,
            access_block=prod.get("access"),
        )


# ---------------------------------------------------------------------------
# Building an InstallConfig from raw version data
# ---------------------------------------------------------------------------


def _build_install_config(
    *,
    product: str,
    version: str,
    ver_data: dict[str, Any],
    prod_summary: str,
    prod_homepage: str,
    prod_platforms: tuple[str, ...],
    allow_deprecated: bool,
    allow_unsupported: bool,
    access_block: dict[str, Any] | None = None,
) -> InstallConfig:
    prefix = f"{product}@{version}"

    status = _require(ver_data, "status", str, prefix=prefix)
    if status not in SUPPORTED_STATUSES:
        raise ConfigError(f"{prefix}: unknown status {status!r}")
    status_reason = str(ver_data.get("status_reason", ""))
    released = str(ver_data.get("released", ""))

    # Hard-fail yanked unconditionally
    if status == "yanked":
        raise ResolutionError(
            f"{prefix} is yanked and cannot be installed."
            + (f" Reason: {status_reason}" if status_reason else "")
        )
    if status == "unsupported" and not allow_unsupported:
        raise ResolutionError(
            f"{prefix} is marked unsupported. Pass --allow-unsupported to override."
            + (f" Reason: {status_reason}" if status_reason else "")
        )
    if status == "deprecated" and not allow_deprecated:
        raise ResolutionError(
            f"{prefix} is deprecated and --allow-deprecated is off."
            + (f" Reason: {status_reason}" if status_reason else "")
        )

    package = _require(ver_data, "package", str, prefix=prefix)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", package):
        raise ConfigError(f"{prefix}: invalid package {package!r}")

    package_version = str(ver_data.get("package_version", version))

    min_python_str = _require(ver_data, "min_python", str, prefix=prefix)
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)", min_python_str)
    if not m:
        raise ConfigError(f"{prefix}: invalid min_python {min_python_str!r}")
    min_python = (int(m.group(1)), int(m.group(2)))

    install_method = _require(ver_data, "install_method", str, prefix=prefix)
    if install_method not in SUPPORTED_INSTALL_METHODS:
        raise ConfigError(f"{prefix}: invalid install_method {install_method!r}")

    required = tuple(_as_list(ver_data.get("required_commands", []), str, prefix=prefix))
    optional = tuple(_as_list(ver_data.get("optional_commands", []), str, prefix=prefix))

    post_raw = ver_data.get("post_install", [])
    if not isinstance(post_raw, list):
        raise ConfigError(f"{prefix}: post_install must be a list")
    post_install: list[PostInstallStep] = []
    for i, step in enumerate(post_raw):
        # Accept either a bare argv list (legacy) or an object with argv + if
        if isinstance(step, list):
            argv = step
            if_expr: str | None = None
        elif isinstance(step, dict):
            argv = step.get("argv", [])
            if_expr = step.get("if")
            if if_expr is not None and not isinstance(if_expr, str):
                raise ConfigError(f"{prefix}: post_install[{i}].if must be a string")
            extra = set(step.keys()) - {"argv", "if"}
            if extra:
                raise ConfigError(f"{prefix}: post_install[{i}] has unknown keys: {extra}")
        else:
            raise ConfigError(
                f"{prefix}: post_install[{i}] must be a list or object, got {type(step).__name__}"
            )
        if not isinstance(argv, list) or not argv:
            raise ConfigError(f"{prefix}: post_install[{i}].argv must be a non-empty list")
        for j, arg in enumerate(argv):
            if not isinstance(arg, str):
                raise ConfigError(f"{prefix}: post_install[{i}].argv[{j}] must be a string")
        # argv[0] is the command name: it should be a bare executable name
        # or absolute path. Reject the textbook shell-wrapper pattern
        # ``["sh", "-c", "...payload..."]`` because that turns argv into a
        # de-facto shell string and undoes the shell=False contract.
        cmd0 = argv[0]
        if (
            _SHELL_WRAPPER_RE.fullmatch(cmd0.lower())
            and len(argv) >= 2
            and argv[1] == "-c"
        ):
            raise ConfigError(
                f"{prefix}: post_install[{i}] uses shell-wrapper form "
                f"({cmd0} -c …); pass commands as argv arrays instead."
            )
        # Reject control characters in any argv element: they shouldn't
        # appear in a legitimate command line and they hint at injection.
        for j, arg in enumerate(argv):
            if any(ord(c) < 0x20 and c not in "\t" for c in arg):
                raise ConfigError(
                    f"{prefix}: post_install[{i}].argv[{j}] contains control characters"
                )
        if if_expr is not None and "=" not in if_expr:
            raise ConfigError(
                f"{prefix}: post_install[{i}].if must be 'key=value', got {if_expr!r}"
            )
        post_install.append(PostInstallStep(argv=tuple(argv), if_expr=if_expr))

    repo: ContentRepo | None = None
    cr = ver_data.get("content_repo")
    if cr is not None:
        if not isinstance(cr, dict):
            raise ConfigError(f"{prefix}: content_repo must be an object or null")
        url = _require(cr, "url", str, prefix=f"{prefix}.content_repo")
        if not (url.startswith("https://") or url.startswith("git@")):
            raise ConfigError(f"{prefix}: content_repo.url must use https:// or git@")
        target = _require(cr, "target", str, prefix=f"{prefix}.content_repo")
        ref = cr.get("ref", "main")
        optional_repo = bool(cr.get("optional", True))
        if not isinstance(ref, str):
            raise ConfigError(f"{prefix}: content_repo.ref must be a string")
        repo = ContentRepo(url=url, target=target, ref=ref, optional=optional_repo)

    prompts_raw = ver_data.get("prompts", [])
    if not isinstance(prompts_raw, list):
        raise ConfigError(f"{prefix}: prompts must be a list")
    prompts: list[Prompt] = []
    for i, p in enumerate(prompts_raw):
        if not isinstance(p, dict):
            raise ConfigError(f"{prefix}: prompts[{i}] must be an object")
        key = _require(p, "key", str, prefix=f"{prefix}.prompts[{i}]")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
            raise ConfigError(f"{prefix}: prompts[{i}].key invalid: {key!r}")
        ptype = _require(p, "type", str, prefix=f"{prefix}.prompts[{i}]")
        if ptype not in ("yes_no", "string", "choice"):
            raise ConfigError(f"{prefix}: prompts[{i}].type invalid: {ptype!r}")
        question = _require(p, "question", str, prefix=f"{prefix}.prompts[{i}]")
        default = p.get("default")
        choices = tuple(_as_list(p.get("choices", []), str, prefix=f"{prefix}.prompts[{i}]"))
        secret = bool(p.get("secret", False))
        if ptype == "choice" and not choices:
            raise ConfigError(f"{prefix}: prompts[{i}]: choice type requires non-empty choices")
        prompts.append(Prompt(
            key=key, type=ptype, question=question,
            default=default, choices=choices, secret=secret,
        ))

    next_steps = tuple(_as_list(ver_data.get("next_steps", []), str, prefix=prefix))

    package_sha = ver_data.get("package_sha256")
    if package_sha is not None and (
        not isinstance(package_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", package_sha)
    ):
        raise ConfigError(f"{prefix}: package_sha256 must be 64 lowercase hex chars")

    access = _parse_product_access(access_block, prefix=f"{product}.access")

    return InstallConfig(
        product=product,
        version=version,
        status=status,
        status_reason=status_reason,
        released=released,
        package=package,
        package_version=package_version,
        min_python=min_python,
        install_method=install_method,
        required_commands=required,
        optional_commands=optional,
        post_install=tuple(post_install),
        content_repo=repo,
        prompts=tuple(prompts),
        next_steps=next_steps,
        package_sha256=package_sha,
        supported_platforms=prod_platforms,
        homepage=prod_homepage,
        summary=prod_summary,
        access=access,
    )


def _parse_product_access(
    access_block: dict[str, Any] | None,
    *,
    prefix: str,
) -> ProductAccess:
    """Parse the per-product ``access`` block from registry.json.

    Returns ``ProductAccess()`` (both fields None) when the block is
    absent. Raises ``ConfigError`` on schema violations.
    """
    if access_block is None:
        return ProductAccess()
    if not isinstance(access_block, dict):
        raise ConfigError(f"{prefix}: must be an object, not {type(access_block).__name__}")

    auth_block = access_block.get("auth")
    auth: AuthAccess | None = None
    if auth_block is not None:
        if not isinstance(auth_block, dict):
            raise ConfigError(f"{prefix}.auth: must be an object")
        kind = str(auth_block.get("kind", "bearer"))
        if kind != "bearer":
            raise ConfigError(
                f"{prefix}.auth.kind: only 'bearer' is supported (got {kind!r})"
            )
        auth = AuthAccess(
            kind=kind,
            required=bool(auth_block.get("required", False)),
            env_var=str(auth_block.get("env_var", "GET_INSTALLER_TOKEN")),
            hint_url=(
                str(auth_block["hint_url"])
                if auth_block.get("hint_url") is not None
                else None
            ),
        )

    signed_block = access_block.get("signed")
    signed: SignedAccess | None = None
    if signed_block is not None:
        if not isinstance(signed_block, dict):
            raise ConfigError(f"{prefix}.signed: must be an object")
        algorithm = str(signed_block.get("algorithm", "HMAC-SHA256"))
        if algorithm != "HMAC-SHA256":
            raise ConfigError(
                f"{prefix}.signed.algorithm: only 'HMAC-SHA256' is supported "
                f"(got {algorithm!r})"
            )
        max_skew = signed_block.get("max_skew_seconds", 60)
        if not isinstance(max_skew, int) or max_skew < 0:
            raise ConfigError(
                f"{prefix}.signed.max_skew_seconds: must be a non-negative int"
            )
        signed = SignedAccess(
            algorithm=algorithm,
            query_param=str(signed_block.get("query_param", "sig")),
            expires_param=str(signed_block.get("expires_param", "exp")),
            max_skew_seconds=max_skew,
        )

    return ProductAccess(auth=auth, signed=signed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require(data: dict[str, Any], key: str, expected: type, prefix: str = "") -> Any:
    if key not in data:
        raise ConfigError(f"{prefix + ': ' if prefix else ''}missing required field {key!r}")
    val = data[key]
    if not isinstance(val, expected):
        raise ConfigError(
            f"{prefix + ': ' if prefix else ''}field {key!r} must be "
            f"{expected.__name__}, got {type(val).__name__}"
        )
    return val


def _as_list(val: Any, item_type: type, prefix: str = "") -> list[Any]:
    if not isinstance(val, list):
        raise ConfigError(
            f"{prefix + ': ' if prefix else ''}expected list, got {type(val).__name__}"
        )
    for i, item in enumerate(val):
        if not isinstance(item, item_type):
            raise ConfigError(
                f"{prefix + ': ' if prefix else ''}item [{i}] must be "
                f"{item_type.__name__}, got {type(item).__name__}"
            )
    return val


_SEMVER_RE = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:[+-](.+))?")


def _semver_key(version: str) -> tuple[int, int, int, int, str]:
    """Sort key for semvers: releases > prereleases of the same triple."""
    m = _SEMVER_RE.fullmatch(version)
    if not m:
        return (0, 0, 0, 0, version)
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre = m.group(4) or ""
    # Releases sort after prereleases at the same triple
    pre_rank = 1 if not pre else 0
    return (major, minor, patch, pre_rank, pre)


def current_platform() -> str:
    """Return the registry's platform string for the running system."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return sys.platform
