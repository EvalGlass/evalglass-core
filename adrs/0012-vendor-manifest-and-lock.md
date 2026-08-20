# ADR 0012 — vendor-manifest.json and evalglass.lock formats

- **Status:** accepted
- **Date:** 2026-05-31

## Context

Vendoring (ADR 0011) copies the managed runtime into `evals/_evalglass/`. Two records
make that boundary reviewable and reproducible (build contract §9/§11): a per-file
manifest (so a re-vendor or audit can detect host patches exactly) and a lock (the
installed runtime identity). Their shapes are public, host-reviewable, and hard to
reverse, so they get an ADR. Implemented in EG-M3-2.

## Decision

`evals/_evalglass/vendor-manifest.json` — `VendorManifest`:

| Field | Meaning |
|---|---|
| `schema_version` | Manifest schema version (`"1"`). |
| `source_version` | The framework version vendored. |
| `managed_root` | `evals/_evalglass` — every managed path lives under it. |
| `files[]` | One `ManagedFileRecord` per managed file: `path` (host-relative), `sha256` (of the **written** bytes), `purpose` (`core`/`harness`/`adapters`/`package`), `host_patched` (set on re-vendor when the on-disk checksum diverges). |

`evals/evalglass.lock` — `EvalglassLock`: `schema_version`, `framework_version`,
`source_ref`, `installed_features` (`["core","harness","adapters"]`), `optional_extras`
(`[]` at M3).

Rules: the manifest records **only** files under `managed_root` (a path outside it, or
one containing `..`, is rejected — a corrupted manifest must never steer a write/remove
at host-owned truth); checksums are over the bytes actually written (LF, via
`write_bytes`) so they are honest cross-platform; both are JSON-primary with fail-closed
`from_dict`/`to_dict`.

## Consequences

- Re-vendor detects host patches and obsolete managed files by diffing the manifest
  against disk; host-owned truth is never recorded or touched.
- The lock pins the framework identity for reproducible re-vendoring/upgrade.
- A new managed file or feature is an additive manifest/lock change, not a new format.

## Alternatives considered

- **A single combined manifest+lock file.** Rejected — the manifest is the managed-file
  boundary (changes every re-vendor); the lock is the install identity (changes on
  upgrade). Separating them keeps each record's purpose and churn distinct.
- **No per-file checksums (just a version).** Rejected — host-patch detection and honest
  re-vendor diffs require per-file content hashes.
