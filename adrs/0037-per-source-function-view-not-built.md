# ADR 0037 — Per-source-function score view is not built (M6 never-build)

- **Status:** accepted
- **Date:** 2026-06-07
- **Source:** final product plan `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §0.4 / §4 (ADR row) /
  §M6-S* (per-source-function explicitly excluded from the build order); remaining product plan
  `jira_tickets_remaining_implementation_plan.xlsx` Non-Goals + EG-R5-1/EG-R5-6
- **Related:** [0031](0031-runner-attach-seam-and-lane-results.md) (the lane side channel),
  the metrics-explorer view (EG-M5C-8)

This ADR records the decision the coverage row `EG-M5C-7` points to: EvalGlass does
**not** build a per-source-function score view in the M6 architecture-alignment
tranche, and the row stays `not_started` with this ADR as its non-empty,
reasoned justification (not a silent gap).

> The final plan §4 originally reserved ADR 0032 for this never-build decision, but
> 0032 was used for the companion-ontology reconciliation workflow. This ADR (0037)
> is the real home for the per-source-function decision; `EG-M5C-7`'s
> `not_exercised_reason` cites it.

## Decision

**Per-source-function attribution is not built.** EvalGlass will not group or attribute
scores to a specific *host source function / call site* (e.g. "metric X for the
`summarize()` function"). The capability stays `planned` and its coverage row
(`EG-M5C-7`) stays `not_started`.

**Why not now.** Per-source-function attribution requires explicit
**trace-to-call-site correlation** — a reliable mapping from a recorded behavior back
to the host source function that produced it. EvalGlass has no such correlation: a
`TraceEnvelope` carries a vendor-neutral `trace_id`/`unit_id`, not a host call-site
identity. Building a view that *guessed* the source function (from names, ordering,
or heuristics) would manufacture an attribution the evidence does not support — the
exact false confidence the project forbids.

**The honest ceiling that IS built.** Grouping is offered only over explicit identity
that the artifacts already carry: `view --by-call` / by-subject grouping over
`(example_id, unit_id)` (the metrics explorer, `EG-M5C-8`). That groups by recorded
identity, never by an inferred call site, and refuses to group artifacts that lack
explicit identity rather than guessing.

**When this could change.** Only when the product gains a real, host-declared
trace-to-call-site correlation (a recorded call-site identity on the
`TraceEnvelope`/`EvalUnit`), proven end-to-end, may a per-source-function view be
reconsidered — as a new ADR, not by relaxing this one.

## Consequences

- `EG-M5C-7` is a reasoned `not_started`, not a silent omission; `egts coverage
  --require-complete` treats it as honestly deferred (a non-empty reason), and the
  R-tranche readiness gate asserts the reason cites this ADR.
- Public docs/status describe per-source-function as `planned` and use only
  `by-call` / `by-subject` wording — never claiming source-function attribution.
- No code is added for this capability; the metrics explorer (`EG-M5C-8`) remains the
  built, identity-grouped view.
