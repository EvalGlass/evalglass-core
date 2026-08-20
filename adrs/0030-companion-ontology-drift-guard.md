# ADR 0030 — Companion-ontology drift guard (vendored artifact, two tracks)

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** alignment test plan `docs/PRODUCT_ARCHITECTURE_TEST_PLAN.md` §D Part 2 (companion ontology), Appendix B; tickets EG-AT5-1…EG-AT5-8
- **Related:** [0029](0029-frozen-spine-snapshots-and-capability-status.md) (frozen public-surface snapshots + capability status), [0017](0017-extension-lane-framework.md) (extension-lane framework)

## Context

A companion **ontology** describes the product as a machine-checkable graph (205
entities · 355 relations · 15 classes · 15 predicates). It lives in the sibling
site repo (`evalglass-site/docs/design/ontology/`) with its own JSON schema and a
JavaScript intra-consistency checker (`check-ontology.mjs`). That checker validates
the artifact against *itself*; it cannot see the live Python code. The artifact is
real but is **not yet a live-code mirror**: some enum entities model product
concepts rather than live enums, and several `repoLocator`s are stale.

The missing piece is a **Python-side code↔ontology drift guard** that runs in this
repo's CI, so a divergence between the ontology and the live contracts is caught
loudly rather than silently believed.

## Decision

1. **Vendor the artifact + schema into this repo** at `docs/design/ontology/`
   (`evalglass-ontology.json`, `evalglass-ontology.schema.json`). The drift guard
   resolves its artifact from `$EVALGLASS_ONTOLOGY` first, then this in-repo copy.
   This lets Track A/B run deterministically in CI; when neither path is available
   the guard **skips with a visible count**, never a silent pass over zero entities.

2. **A stdlib-only, fail-closed loader** (`tests/ontology/ontology_loader.py`)
   mirrors the artifact's own schema's structural rules (required keys, the
   `^prefix.suffix` id pattern, the closed `status`/`verification` vocabularies,
   unique ids, no dangling relation endpoints, known predicates). **No `jsonschema`
   dependency is added** to the framework — the ontology guard is test-tier only and
   `src/evalglass/**` never imports it.

3. **Two tracks.** *Track A* validates the artifact exactly as it exists today.
   *Track B* reconciles the artifact against live code (enums, ADRs, ports, lanes,
   invariants, `repoLocator`s) and is green only when the produced drift equals a
   committed **expected-drift manifest**. The manifest pins the known, intentional
   drift (e.g. `enum.authority` models the resolution ladder, not `AuthorityLevel`;
   `enum.data-policy` omits `forbidden`/`missing`/`unknown`; the live
   `ThresholdApproval`/`JudgeCalibration`/`LaneStatus`/`LanePort`/`Maturity` enums
   are not modeled as entities yet). After the site artifact is remediated, manifest
   entries are removed until it is empty.

## Consequences

- The drift guard is a test-tier artifact: it never gates a host run and adds no
  runtime dependency. It is selectable as `pytest -m ontology` and runs in the
  `docs-consistency` CI job.
- The vendored copy must be kept in sync with the sibling site repo; a divergence
  is itself drift the guard surfaces.
- Remediating the ontology (correcting enums, locators, adding missing entities)
  shrinks the expected-drift manifest — the manifest is the explicit, reviewable
  record of what still differs.
