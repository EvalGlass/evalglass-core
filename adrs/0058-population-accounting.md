# ADR 0058 — First-class per-metric population accounting

**Status:** Accepted

## Context

A metric's value did not say how much of its intended population it actually measured. The Scorecard
carried an aggregate value, an `included_count`, and raw `status_counts`, but "coverage", "metric
count", and "quality" were easy to conflate: a metric that validly scored 1 of 100 eligible subjects
looked, at a glance, indistinguishable from one that scored all 100. The plan (`EvaluationPlan`)
already resolved a per-metric pre-effect ledger (available / selector-matched / eligible / excluded),
but it was not persisted per metric, so no artifact reconciled the planned population, the executed
effects, and the raw scores under one set of definitions.

## Decision

Introduce a typed, additive **`PopulationSummary`** (core contract, `core/population.py`), one per
metric on the Scorecard, that reconciles two layers by stable subject identity.

- **Terminal layer (score-derived, always known).** `scored_valid`, `non_evaluable`, `blocked`,
  `skipped`, `error` are computed by the core from the raw scores. Counts are over *emitted scores*
  (a batch evaluator, the synthetic selector-no-match score, and the run-integrity route-error score
  each count once); a `scored` measurement whose validity is not `valid` is counted as `error` (an
  invalid measurement is a failure, never a value). This layer is a **verified projection**:
  `RunRecord` recomputes it on load and rejects a record whose stored terminal counts contradict its
  raw scores — so a blocked/non-evaluable subject can never be laundered into a numeric zero or
  hidden behind a surviving score.
- **Pre-effect layer (plan-derived).** `available`, `selector_matched`, `selector_excluded`,
  `eligible`, `prerequisite_excluded` are supplied by the Harness from the plan after the core
  returns. Their reconciliation identities (`available == selector_matched + selector_excluded`,
  `selector_matched == eligible + prerequisite_excluded`) are enforced at construction. On a legacy
  record or a core-only scorecard this layer is **unknown (`None`), never fabricated as zero** — the
  fields are omitted from the serialized form and the record still loads.
- **Coverage, never a quality composite.** The summary deliberately defines no default overall score:
  it distinguishes source coverage (available/matched) from measurement coverage (scored_valid) so a
  partially-evaluable metric cannot render as fully covered. `PopulationSummary.measured` is `True`
  only when at least one subject reached a valid measurement.
- **One definition set for every renderer.** The Markdown report renders an Evaluability section from
  the typed summary; JSON carries it directly; the diagnostic dashboard (a later change) consumes the
  same fields — no renderer recomputes or redefines the counts.

## Consequences

- `available`/`matched`/`eligible`/`scored_valid` reconcile the plan, the effects, and the raw scores
  in one place, so a developer can see how many subjects a metric could and did measure.
- Anti-tamper coverage extends to the derivable (terminal) layer; the plan-derived layer is
  internally identity-checked and covered by the existing artifact manifest/marker integrity.
- Additive and backward-compatible: `populations` is emitted only when non-empty, so a scorecard
  without it is byte-identical, and a legacy record marks pre-effect counts unknown rather than zero.
