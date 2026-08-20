# Companion ontology (vendored)

`evalglass-ontology.json` is the machine-checkable companion ontology for EvalGlass —
entities (layers, ports, contracts, enums, invariants, …) and their typed relations —
validated against `evalglass-ontology.schema.json`. It is a **data artifact**, not runtime
code; nothing under `src/**` imports it.

## Reconciliation status (EG-H1, ADR 0032)

This vendored copy has been **reconciled to the live product vocabulary**. Track B (the
code↔ontology drift guard, `tests/ontology/`) is **strict**: both expected-drift manifests
are empty, so the ontology's `Enum` entities mirror the live Python enums and every non-null
`repoLocator` resolves to a real repo path.

- **Enums:** `enum.authority` models `AuthorityLevel` (`none/informational/gating`) — the
  `informational/blocked/can_gate` *resolution ladder* is a separate concept, not enum
  members; `enum.data-policy` and `enum.exit-class` carry their full live member sets; and
  `ThresholdApproval`, `JudgeCalibration`, `LanePort`, `LaneStatus`, `Maturity` are modeled.
  Seven live enums remain intentionally unmodeled (`Aggregation`, `Direction`,
  `JudgeEvidenceStatus`, `Lens`, `ScoreType`, `Severity`, `UnitKind`) — recorded as the
  master-guard exception set, out of scope for this tranche.
- **repoLocators:** the formerly-stale fake-judge / judge-collection / evaluator-protocol /
  calibration-record / vendored-runtime locators now point at real paths.

## Source-of-truth note (standing follow-up)

ADR 0030 established the upstream source of truth as the sibling **`evalglass-site`** repo
(with its `build-*.mjs` generator), re-vendored here. EG-H1 was performed by editing **this
vendored copy directly** because that source was unavailable in the build environment, so —
until the upstream is re-synced — **this in-repo copy leads** (a recorded, temporary
inversion of ADR 0030; see ADR 0032). The standing follow-up: apply the same reconciliation
to the `evalglass-site` source, regenerate, and re-vendor, confirming a byte-identical copy.
