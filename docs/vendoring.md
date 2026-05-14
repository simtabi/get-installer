# Vendoring the installer into another project

The whole `get-installer/` folder is **self-contained**. You vendor it
into another project by copying the directory and editing one file
(`registry.json`).

## Step 1 — Copy

```bash
# From this repo:
cp -r installer/ ~/projects/your-new-tool/installer
```

Or via git subtree / sparse-checkout if you want to track upstream
changes. The installer has zero runtime deps beyond Python stdlib so
plain `cp` is fine.

## Step 2 — Edit `registry.json`

```json
{
  "schema_version": 2,
  "registry_updated": "2026-01-15",
  "products": {
    "your-new-tool": {
      "name": "your-new-tool",
      "summary": "Short pitch sentence ending with a period.",
      "homepage": "https://opensource.simtabi.com/products/your-new-tool",
      "default_version": "0.1.0",
      "supported_platforms": ["linux", "darwin", "windows"],
      "versions": {
        "0.1.0": {
          "status": "current",
          "released": "2026-01-15",
          "package": "your-new-tool",
          "min_python": "3.10",
          "install_method": "auto",
          "required_commands": ["git"],
          "post_install": [
            ["your-new-tool", "init"]
          ]
        }
      }
    }
  }
}
```

Full field reference: [`config-schema.md`](config-schema.md).

## Step 3 — Edit the bootstrap defaults

If you want a one-liner like
`sh -c "$(curl -fsSL https://get.simtabi.com/your-tool.sh)"`,
host `install.sh` + `installer.py` + `registry.json` at that URL.
The default `INSTALLER_BASE_URL` is `https://get.simtabi.com`
— change the constant near the top of `install.sh` (and the param
default in `install.ps1`) if you host elsewhere.

## Step 4 — Test

```bash
python -m get_installer --list
python -m get_installer --product your-new-tool --dry-run --yes
```

Run the suite:

```bash
pytest tests/
```

## Step 5 — Distribute

Two endpoints:

1. **Simtabi-hosted**:
   `https://get.simtabi.com/<your-tool>/v<version>/install.sh`
2. **GitHub release asset**:
   `https://github.com/<org>/<repo>/releases/download/v<version>/install.sh`

Both serve the same files. Pin via `INSTALLER_SHA256` env var (Unix)
or `-InstallerSha256` parameter (PowerShell) for tamper detection.

## What you DON'T need to touch

| File | Why not |
|---|---|
| `core/*.py` | Reusable engine; same for every project. |
| `bootstrap/install.sh` / `install.ps1` | Generic. Reads `registry.json` you provide. |
| `schemas/registry.schema.json` | Authoritative; don't fork. |
| `tests/*.py` | Cover the engine, not your registry. |

If you find yourself wanting to fork `core/`, surface that upstream
first — most reasonable extensions belong in the engine itself, not
in per-project forks.

## Compatibility promise

The installer engine follows semver. v1 promises the
`schema_version: 2` registry shape and the CLI flags documented in
`config-schema.md` will keep working through every v1.x.

When v2 ships, it will read both v2 and v1 registries; v1 will read
only v1.
