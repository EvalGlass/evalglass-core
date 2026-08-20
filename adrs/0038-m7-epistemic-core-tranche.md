# ADR 0038 — M7 "Epistemic Core": level up alpha's measurement without shedding its breadth

- **Status:** accepted
- **Date:** 2026-07-17
- **Source:** `docs/TETA_REDESIGN.md`, `docs/TETA_IMPLEMENTATION_PLAN.md` (milestone M7,
  tranches T0–T9); the DAFO assessment (`dafo-evalglass-assessment/EVALGLASS_BETA_FULL_AUDIT.md`,
  `EVALGLASS_REDESIGN_PERSPECTIVE.md`, `DAFO_EVALGLASS_IMPROVEMENT_AUDIT.md`)
- **Related:** the score contract (`core/scores.py`), authority (`core/authority.py`),
  verdict (`core/verdict.py`), provenance (`core/provenance.py`), aggregation
  (`core/aggregation.py`), calibration (`harness/calibration.py`); the isolation gate
  ([0001](0001-effect-boundary.md) family); this tranche's per-slice ADRs follow (0040+).

This ADR records the *framing decision* for the M7 tranche so the individual
slice ADRs (Estimate schema, DecisionPolicy, digest-bound AuthorityGrant, per-run
catalog, atomic persistence, schema bumps) inherit one rationale.

## Context

An independent audit of alpha against a full host loop (`dafo-agentic-finance`)
and a lean rebuild (`evalglass-beta`) concluded that alpha's epistemics **stop at
the point estimate**: aggregation emits a bare scalar with coverage counts but no
uncertainty; the verdict compares that point estimate directly to a threshold;
authority is inline enum tokens not bound to the artifacts they approve; a *fake*
judge can gate given a hand-written calibration file; calibration is *declared*,
not *computed*; baselines gate on a comparability boolean with no paired delta;
and core isolation is proven by AST scan only. The book itself never develops
confidence intervals, decision policy, computed calibration, or study design — so
this is a genuine ceiling, faithfully implemented, not a regression to restore.

The audit's recommendation was to **drop alpha's machinery** (installer,
vendoring, ports, lanes, connectors, governance) and adopt the lean beta.

## Decision

**M7 keeps alpha's breadth and raises its epistemic ceiling.** We reject the
"delete the machinery" half of the audit and accept the "raise the rigor" half.

1. **Preserve, unchanged in contract:** the effect-free stdlib-only Core; the
   never-0.0 score encoding with the full `ScoreStatus` × `Validity` model (we do
   **not** collapse to a single boolean); the self-re-checking `VerdictPayload`;
   the 10-dimension structured provenance and its 6 gating dimensions; the
   two-stage fail-closed authority ladder; the single Verdict Engine and exit-code
   mapping; vendoring/installer; ports, deletable extension lanes, sinks,
   governance; the Langfuse/Phoenix/LangSmith connectors, `TraceEnvelope`
   normalization, and the call/step/trajectory/session unit ladder; core-isolation,
   absent-verb identity, and honest maturity vocabulary. Real target hosts (the
   next milestone is a Langfuse-traced host) need this breadth; DAFO did not, which
   is why the audit undervalued it.

2. **Build a new epistemic center of gravity** across the spine, additively:
   a first-class `Estimate` with honest intervals (Wilson/Jeffreys/mean) and a
   `min_samples` floor; a fingerprinted `DecisionPolicy` (`decision_statistic` ∈
   {point, lower_confidence_bound, upper_confidence_bound}, `min_n_effective`,
   `max_missing_fraction`, `required_study`); capability-typed judge authority (a
   fake judge can *never* gate, before any calibration is considered); a
   **digest-bound** `AuthorityGrant` content-addressed over the policy, dataset
   validation, evaluator capability, study, and threshold it approves; a
   **computed and verified** judge agreement study (confusion, Cohen κ, order-bias,
   self-proving arithmetic) that supersedes declared calibration; a per-run
   `EvaluatorCatalog` carrying implementation digests; **executable** import
   isolation; load-time recomputation of aggregates/estimates/verdicts from raw
   scores plus atomic persistence; paired baseline comparison over shared items;
   and an optional `ClaimSpec` construct/validity record. Several of these are
   ahead of *both* alpha and the hardened beta.

## Constraints (bind every M7 slice)

- Core stays effect-free and stdlib-only (`dataclasses, enum, typing, json,
  hashlib, math`; `decimal` only if exact threshold arithmetic requires it). The
  new `studies/` package is **pure** (stdlib-only), not a third effect tier.
- **No new required dependency.** Optional lanes keep their pinned, isolated,
  deletable extras.
- All new fields are **optional and additive**; existing `evalglass.scorecard` /
  `evalglass.runrecord` JSON must still parse. Where semantics change, bump the
  schema version with a migration/tolerance note in that slice's ADR.
- No new false-green surface: a fake judge, a mismatched grant, a one-item gate, a
  tampered persisted record, and a non-comparable baseline must each be provably
  unable to produce a `pass`.

## Consequences

teta grows in the core (new types and study methods) while its host-facing breadth
and public API remain compatible. The measurement claims a green Scorecard is
allowed to carry become stronger *and* more honest: every gate names the
estimator, decision boundary, effective n, and reliability rule that licensed it.
The alternative — a lean rebuild — was rejected because it would discard the
connector/trace/lane machinery that real hosts, unlike DAFO, depend on.
