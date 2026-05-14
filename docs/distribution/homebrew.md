# Homebrew tap distribution

A Homebrew tap is a complementary distribution channel to the
registry-driven `curl | sh` installer. Users on macOS / Linux who prefer
Homebrew can run:

```bash
brew install simtabi/tap/<product>
```

This page walks through setting up the tap for `get-installer` itself
and for any product registered in `registry.json`.

## Live formula

The ready-to-ship formula lives at
[`templates/homebrew-formula/get-installer.rb`](../../templates/homebrew-formula/get-installer.rb).
On every PyPI release, the same file (with updated `url` + `sha256`)
lands in `simtabi/homebrew-tap/Formula/get-installer.rb`.

`get-installer` is stdlib-only, so no `resource` blocks are needed.
The `test do` block exercises `--version`, `--list`, and a clean
failure on an unknown product.

## When to use the tap

| Situation | Best channel |
|---|---|
| Fresh-machine bootstrap on any OS | `curl | sh` (registry-driven) |
| User already has Homebrew + pinned Python | `brew install` |
| Air-gapped / locked-down environment | Vendored bundle (`docs/vendoring.md`) |
| CI image build | Bundled `installer.py` or `pip install` |

The tap is for users who *prefer* Homebrew as their package manager. It
is not a replacement for the registry-driven installer.

## Initial setup (one-time per tap)

1. Create the `simtabi/homebrew-tap` repository on GitHub (empty,
   public, with a `Formula/` directory).

2. Tap it locally:

   ```bash
   brew tap-new simtabi/tap
   ```

3. For each product, generate the initial formula. Replace
   `{package}`, `{X.Y.Z}`, and the URL with values for the product:

   ```bash
   brew create --python --tap simtabi/tap \
     https://files.pythonhosted.org/packages/source/{first}/{package}/{package}-{X.Y.Z}.tar.gz
   ```

4. Auto-generate resource blocks from `pyproject.toml`:

   ```bash
   brew update-python-resources Formula/{package}.rb
   ```

5. Lint:

   ```bash
   brew style --fix Formula/{package}.rb
   brew audit --new --strict Formula/{package}.rb
   ```

6. Commit + push to `simtabi/homebrew-tap`.

The starter scaffold at [`templates/homebrew-formula.rb.template`](../../templates/homebrew-formula.rb.template)
documents every placeholder.

## Ongoing releases (automated)

Once the tap exists, the release workflow in each product repo should
bump the tap on every published tag. The pattern (in
`.github/workflows/release.yml`):

```yaml
- name: Bump Homebrew tap
  uses: dawidd6/action-homebrew-bump-formula@v3
  with:
    token: ${{ secrets.TAP_GITHUB_TOKEN }}
    tap: simtabi/homebrew-tap
    formula: {package}
    tag: ${{ github.ref_name }}
    revision: ${{ github.sha }}
```

`TAP_GITHUB_TOKEN` is a PAT with `repo` scope on `simtabi/homebrew-tap`
(or a fine-grained token scoped to that repo's contents). The action
opens a PR that updates `url` and `sha256`; merge it after CI passes.

## Smoke test

The formula's `test do` block must verify the binary works. The
template stub is:

```ruby
test do
  assert_match version.to_s, shell_output("#{bin}/{entrypoint} --version")
end
```

For tools that have a side-effect-free `doctor`, `validate`, or
`status` verb, invoke it too. A broken default-config path fails
`brew test` before users hit it.

## Limitations

- **Python pin**: the template depends on `python@3.12`. Update to the
  current Homebrew default before publishing a new formula.
- **No `from-source` builds**: Homebrew installs from sdist by
  default. If a product ships compiled extensions, add `bottle do`
  blocks per CPU architecture.
- **Tap is OS-agnostic but tested on macOS only**: Linuxbrew works the
  same way but each formula should be smoke-tested on a Linux runner.

## See also

- [`templates/homebrew-formula.rb.template`](../../templates/homebrew-formula.rb.template) (scaffold)
- [Homebrew tap docs](https://docs.brew.sh/Taps)
- [`brew create --python` reference](https://docs.brew.sh/Python-for-Formula-Authors)
