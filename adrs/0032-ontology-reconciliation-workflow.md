# ADR 0032 — Companion-ontology reconciliation: edit the vendored copy, strict Track B, deferred source sync

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** final product plan `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §0.5 / §M6-S9–S11; tickets EG-H1-1 … EG-H1-6 (`jira_tickets_alignment_foundation_hermetic.xlsx`)
- **Related:** [0030](0030-companion-ontology-drift-guard.md) (companion-ontology drift guard, vendored artifact, two tracks)

## Context

ADR 0030 vendored the companion ontology (`docs/design/ontology/evalglass-ontology.json`)
and stood up the two-track drift guard. Track A validates the artifact's own shape;
**Track B** compares the ontology's `Enum` entities to the live Python enums and is
green only while the produced drift **equals a committed expected-drift manifest**
(`tests/ontology/expected_enum_drift.json`, `expected_repolocator_drift.json`). That
manifest currently pins **known, intentional drift** — it documents the gap, it does
not close it:

- three member mismatches (`enum.authority` models the resolution ladder rather than
  `AuthorityLevel`; `enum.data-policy` omits `forbidden/missing/unknown`;
  `enum.exit-class` uses exit codes `0/1/2` rather than the `ExitClass` names);
- five live enums the ontology does not model yet (`ThresholdApproval`,
  `JudgeCalibration`, `LanePort`, `LaneStatus`, `Maturity`);
- five stale `repoLocator`s pointing at paths that no longer exist.

The plan's intent (§0.5) is **zero unexplained drift**: reconcile the ontology to the
live code, then make Track B strict. Two facts shape *how* we do it here:

1. The ontology's upstream source of truth lives in the **sibling `evalglass-site`
   repo** (with its `build-*.mjs` generator + `check-ontology.mjs`), which is **not
   present in this build environment** — only the vendored copy and its JSON schema are.
2. Track B is an equality check, so an artifact edit and the corresponding manifest
   shrink **must land together** or the guard goes red.

## Decision

**1. Reconcile by editing the vendored in-repo artifact directly.** Because the
`evalglass-site` source is unavailable here, the canonical reconciliation for this
tranche edits `docs/design/ontology/evalglass-ontology.json` in place — fixing the
three member mismatches, adding the five missing `Enum` entities (each with its
`EnumValue` entities, `hasValue` relations, and updated `stats`/`byClass` counts), and
correcting the five stale `repoLocator`s. The artifact stays valid against its own
`evalglass-ontology.schema.json` and the Track A loader.

**2. The reconciled vendored copy is the source of truth until upstream is re-synced.**
This **temporarily inverts** ADR 0030's "vendored copy mirrors the site source" flow.
The site repo must later adopt the same reconciliation (regenerate + re-vendor and
confirm a byte match); until then the in-repo copy leads. This deferral is recorded
here so the divergence is explicit, never silent.

**3. Track B becomes strict, dimension by dimension.** As each drift category is
closed, its expected-drift manifest entry is removed **in the same commit** as the
artifact edit. When a manifest is emptied, Track B for that dimension is strict
equality. The bidirectional master guard's `_UNMODELED_LIVE_ENUMS` exception set loses
exactly the five now-modeled enums; the remaining seven (`Aggregation`, `Direction`,
`JudgeEvidenceStatus`, `Lens`, `ScoreType`, `Severity`, `UnitKind`) stay excepted —
they are out of scope for this tranche and remain honestly recorded, not pretended-away.

**4. The reconciliation models meaning, not just tokens.** `AuthorityLevel` is modeled
as its three live members (`none/informational/gating`); the `informational/blocked/
can_gate` resolution **ladder** is a separate concept (`ResolvedAuthority.level` + the
two booleans), not enum members. `ExitClass` is modeled by its names; the `0/1/2` exit
**codes** are a mapping, not enum values. This keeps the ontology faithful to the
typed contracts the spine actually exposes.

## Consequences

- `pytest -m ontology` reports **zero unexplained drift**: the artifact mirrors the
  live enums and locators, the manifests are empty, and the master guard confirms every
  live enum is mapped or explicitly excepted.
- The reconciliation is a **data + test-tier change only** — no `src/**` runtime code
  moves; the effect-free core and the spine are untouched.
- There is a **standing follow-up**: re-sync the `evalglass-site` source ontology
  (regenerate and re-vendor, confirming a byte-identical copy). Until that lands, the
  in-repo copy is authoritative — a known, recorded inversion of ADR 0030.
- If the live enum vocabulary changes later, the master guard fails closed (a new live
  enum that is neither mapped nor excepted), forcing a deliberate ontology update.
