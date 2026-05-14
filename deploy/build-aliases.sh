#!/usr/bin/env sh
# Generate per-product / per-version convenience aliases under /srv/www/
# from registry.json.
#
# Result: /srv/www/<product>/install.sh and /srv/www/<product>/<version>/install.sh
# each pre-set --product (and --version where applicable) via a thin shim.

set -eu

WWW="${WWW:-/srv/www}"
REGISTRY="${REGISTRY:-${WWW}/registry.json}"

if [ ! -f "$REGISTRY" ]; then
    echo "build-aliases: $REGISTRY missing; skipping" >&2
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "build-aliases: python3 not on PATH; skipping" >&2
    exit 0
fi

python3 - "$WWW" "$REGISTRY" <<'PY'
import json, os, stat, sys
www, registry_path = sys.argv[1], sys.argv[2]
with open(registry_path, encoding="utf-8") as f:
    reg = json.load(f)

POSIX_TEMPLATE = """#!/usr/bin/env sh
# Auto-generated alias for {product}{version_marker}.
# This is the same script as /install.sh with --product preset.
exec sh -c "$(curl -fsSL ${{INSTALLER_BASE_URL:-https://get.simtabi.com}}/install.sh)" \\
    -- --product {product}{version_flag} "$@"
"""

PS_TEMPLATE = """# Auto-generated alias for {product}{version_marker}.
$args = @('-Product', '{product}'{version_arg}) + $args
& ([scriptblock]::Create((irm ${{env:INSTALLER_BASE_URL ?? 'https://get.simtabi.com'}}/install.ps1))) @args
"""

for product, prod in (reg.get("products") or {}).items():
    base = os.path.join(www, product)
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "install.sh"), "w", encoding="utf-8").write(
        POSIX_TEMPLATE.format(product=product, version_marker="",
                              version_flag="")
    )
    open(os.path.join(base, "install.ps1"), "w", encoding="utf-8").write(
        PS_TEMPLATE.format(product=product, version_marker="",
                           version_arg="")
    )
    for version in (prod.get("versions") or {}).keys():
        vdir = os.path.join(base, version)
        os.makedirs(vdir, exist_ok=True)
        open(os.path.join(vdir, "install.sh"), "w", encoding="utf-8").write(
            POSIX_TEMPLATE.format(
                product=product, version_marker=f" {version}",
                version_flag=f" --version {version}",
            )
        )
        open(os.path.join(vdir, "install.ps1"), "w", encoding="utf-8").write(
            PS_TEMPLATE.format(
                product=product, version_marker=f" {version}",
                version_arg=f", '-Version', '{version}'",
            )
        )
        for fn in ("install.sh", "install.ps1"):
            p = os.path.join(vdir, fn)
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    for fn in ("install.sh", "install.ps1"):
        p = os.path.join(base, fn)
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

print(f"build-aliases: wrote aliases for {len(reg.get('products') or {})} product(s)")
PY
