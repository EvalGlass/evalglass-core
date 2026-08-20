# ADR 0028 — `authority.json` is a host-owned ledger; the runtime never reads it

- **Status:** accepted
- **Date:** 2026-06-05
- **Source:** alignment test plan `docs/PRODUCT_ARCHITECTURE_TEST_PLAN.md` §1.2/§3.7; ticket EG-AT0-7 (AUTH-LEDGER-DECISION gate)

## Context

The installer scaffolds `evals/authority.json` as an empty
`AuthorityRecord` (`approved_thresholds`, `validated_datasets`,
`calibrated_judges`). It is natural to assume this file is *the* runtime source
of gating authority. It is not. The M4 calibration design routed approval into
two other host-owned surfaces: `evalglass.yaml` (per-metric `metric_status`,
`threshold_approval`, dataset `status`) and `calibration/*.json` (judge
calibration + approved thresholds). A grep confirms it: no module under
`src/evalglass/core`, `harness`, or `adapters` reads `authority.json` — the
symbol lives only in `installer/` (scaffold + contracts).

Leaving this implicit is a false-confidence hazard for the alignment test
fixtures: a test that *populated* `authority.json` and expected a gate to
activate would either pass for the wrong reason or mis-model how authority
flows. The decision must be explicit before authority fixtures are trusted.

## Decision

`evals/authority.json` is a **host-owned audit ledger only**. The vendored
runtime resolves gating authority exclusively from `evalglass.yaml` and
`calibration/*.json`; it **never reads `authority.json`**. An empty (default)
ledger therefore means "no human approval recorded here" — it does not, by
itself, grant or deny a gate, because the runtime does not consult it.

Consequences for tests and fixtures:

- Fresh-host fixtures treat the scaffolded empty `authority.json` as the
  no-authority default, and grant gating authority (where a state needs it)
  through `evalglass.yaml` + `calibration/*.json`, never by editing the ledger.
- No fixture infers gating authority from the ledger.
- A regression guard asserts (a) no runtime module references `authority.json`
  / `AuthorityRecord`, and (b) populating the ledger does not change a verdict.

This is a **documentation/test decision**: it changes no product runtime code.
If a future product change makes the runtime *load* `authority.json`, that is a
new public-contract decision requiring its own ADR (and conflict/precedence
rules against `evalglass.yaml`); this ADR is then superseded.

## Consequences

- The ambiguity is resolved and encoded as a test, so a fresh install's first
  run is honestly informational for the right reason.
- The ledger remains useful as a human-readable, host-owned approval record and
  a future migration anchor, without being a hidden second authority path.
- A green fixture can never quietly imply that the ledger gated a run.
