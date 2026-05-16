# ADR-0001 — Sigstore key management

**Status**: Accepted (2026-05-16)
**Phase**: SPEC §4 Phase F — signed releases via sigstore
**Unblocks**: `verify.sign_bundle_with_sigstore` implementation

## Context

Phase F ships a sigstore-signed `installer.py` bundle so an
operator can verify the binary they're about to pipe into `sh`
came from this repo, not from a tampered mirror. The scaffold
shipped in v0.4.0 (commit `433d7e1`) but the actual signing flow
was blocked on three open questions:

1. **Which signing identity?** sigstore's identity-based signing
   ties a signature to an OIDC subject. Options: maintainer's
   personal GitHub identity, a service account, the repo's GitHub
   Actions workflow identity, or a hybrid.
2. **Where does the public verification key live?** Sigstore uses
   Rekor for public transparency log entries; verification doesn't
   need a pre-shared public key, but operators need to know what
   identity to trust.
3. **Rotation cadence?** If we use a long-lived signing identity,
   when do we rotate it? If we use a short-lived workflow
   identity, what happens to old signatures when the workflow
   moves?

## Decision

### 1. Identity: GitHub Actions workflow OIDC subject

Sign from the release workflow only, using the workflow's OIDC
identity:

```
repo:simtabi/get-installer:ref:refs/tags/v*
```

This is sigstore's "keyless" flow: no long-lived signing key
exists. The signature is bound to an ephemeral certificate issued
by Fulcio for the duration of the workflow run, recorded in
Rekor. Verification proves "this artifact was signed by a release
workflow on `simtabi/get-installer` targeting a `v*` tag at the
time recorded in Rekor."

### 2. Verification: documented OIDC subject

`SECURITY.md` and the bundle's sidecar `installer.py.sigstore`
both name the expected subject. Operators verify with:

```bash
sigstore verify identity \
  --bundle installer.py.sigstore \
  --cert-identity 'https://github.com/simtabi/get-installer/.github/workflows/release.yml@refs/tags/v0.4.0' \
  --cert-oidc-issuer 'https://token.actions.githubusercontent.com' \
  installer.py
```

The `--cert-identity` URL includes the exact tag, so an attacker
who managed to sign a malicious `installer.py` from a feature
branch wouldn't pass verification.

### 3. Rotation: not applicable

No long-lived keys = nothing to rotate. The trust anchor is the
GitHub Actions OIDC issuer, which Sigstore re-roots via Fulcio's
public root every ~6 months. Tooling updates handle that
transparently.

When a release workflow is renamed or moved, old signatures
remain verifiable against the historical identity (Rekor entries
are immutable). The verification command in the consumer docs
must reference the SAME path the signature was minted under.

## Consequences

### What this enables

- `verify.sign_bundle_with_sigstore(path, dry_run=False)` can be
  implemented. The implementation calls
  `sigstore-python`'s `sign` command via subprocess (the python
  API is also fine; we go subprocess to match the rest of our
  signing flow which is shell-readable).
- Release workflow gains a `sign` step between the bundle build
  and the GitHub release attachment. The `.sigstore` file is
  uploaded alongside `installer.py`.
- `docs/security.md` gets a "Verifying the bundle" subsection.

### What this costs

- A new optional dep (`sigstore>=3.0`) — already scaffolded via
  the `[sigstore]` extras.
- Release workflow gets one more required permission:
  `id-token: write` (already there for PyPI trusted publishing,
  no new grant needed).
- Renaming `release.yml` after a release retroactively breaks
  the verification command for prior signatures. Mitigation:
  document this in `SECURITY.md` + keep the file name forever.

### What this doesn't fix

- A compromised GitHub Actions runner can still sign whatever it
  wants while the workflow runs. Sigstore signing is a transparency
  layer, not an attestation that the build was reproducible. For
  reproducibility, see the `bundle.py --check` reproducibility
  test (already gated in CI).

## Implementation

```python
# Inside verify.sign_bundle_with_sigstore:
import subprocess
result = subprocess.run(
    ["sigstore", "sign", "--bundle", f"{bundle_path}.sigstore", str(bundle_path)],
    capture_output=True, text=True, check=False, timeout=120,
)
if result.returncode != 0:
    raise SecurityError(f"sigstore sign failed: {result.stderr.strip()}")
return bundle_path.with_suffix(bundle_path.suffix + ".sigstore")
```

The 120-second timeout matches sigstore's typical Fulcio + Rekor
round-trip latency with headroom.

## Alternatives considered

### Long-lived GPG key (rejected)

Owner: maintainer. Rotation: annual. Public key: published in
SECURITY.md.

**Why rejected:** key rotation is operationally painful; key
revocation has no good story when the maintainer changes; GPG
verification has worse UX than `sigstore verify`.

### Cosign with a static keypair (rejected)

Same pros/cons as GPG with slightly better tooling.

**Why rejected:** still requires a long-lived secret on disk
somewhere. Sigstore keyless removes that whole class of
operational risk.

### Per-maintainer identity (rejected)

Each maintainer's personal GitHub OIDC signs releases.

**Why rejected:** maintainer comings + goings are a real concern
over the project lifetime. Workflow identity outlives any single
maintainer.

## Next steps

1. Land the `sign_bundle_with_sigstore` implementation behind the
   existing `dry_run=False` path.
2. Wire the sign step into `.github/workflows/release.yml` after
   the bundle build, before the GitHub release attachment.
3. Update `SECURITY.md` with the verification command + cert
   identity URL.
4. Add a `tests/test_verify.py::test_sigstore_smoke` test that
   asserts the sign step works against a real Fulcio endpoint
   (skipped unless `INTEGRATION_SIGSTORE=1` in env, since it
   needs network + OIDC). Document the skip rationale.

Tracked in the `[sigstore]` extras + the
`verify.sign_bundle_with_sigstore` symbol shipped in v0.4.0.
