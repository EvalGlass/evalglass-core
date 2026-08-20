# ADR 0044 — Interval bounds are rounded to a platform-independent precision

- **Status:** accepted
- **Date:** 2026-07-22
- **Related:** the M7 epistemic core ([0038](0038-m7-epistemic-core-tranche.md)); the honest
  interval estimators (`core/statistics.py`), the `Estimate`/`Interval` schema
  (`core/estimate.py`), baseline comparability (`core/comparison.py`), and the golden
  artifact engine (`tests/egts/golden.py`).

## Context

M7's `Estimate` adds a confidence interval on top of the point estimate. The bounds are
computed in `core/statistics.py` — the Wilson score interval uses `math.sqrt` and the
standard-normal quantile; the Student-t mean interval uses an incomplete-beta / bisection
t-quantile. Those results are then written **verbatim** into the public `RunRecord` and
`Scorecard` JSON as full-precision (`repr`) floats, e.g. `"lower": 0.2065493143772375`.

`sqrt` and the transcendental helpers behind these estimators are not bit-identical across
platforms: macOS/arm64 and Linux/x86_64 disagree in the last ULP (~1e-16). That has two
consequences, both of which violate stated goals:

1. **Non-reproducible artifacts.** The golden-artifact engine (`tests/egts/golden.py`)
   documents the typed JSON as "byte-deterministic … masked by nothing". It is not: goldens
   generated on one platform drift against another (observed: green on macols/arm64, `2 failed`
   on the Linux CI runners, on `runrecord.json` for both scenarios).
2. **Spurious baseline deltas.** M7's whole point is honest comparison. A paired baseline
   comparison across two platforms would report a non-zero delta on the interval bound that is
   pure floating-point noise, not a real change — false signal in exactly the surface built to
   avoid it.

## Decision

**Round computed interval bounds to a fixed 12 decimal places at their source in
`core/statistics.py`**, via a single `_stable()` chokepoint applied to the return of
`wilson_interval` and `mean_interval` (including the zero-variance mean case).

- Rounding happens **at computation**, not at serialization, so the *same* value is what the
  Verdict Engine gates on, what a baseline compares, and what the JSON serializes — one source
  of truth, no gate/report divergence.
- 12 places is far more precision than any confidence interval needs (bounds live in `[0, 1]`
  for proportions and within a metric's declared range for means) while sitting ~4 orders of
  magnitude above the ~1e-16 ULP noise it erases, so the rounding is unambiguous on every
  platform.
- The point estimate is left unrounded: it comes from `aggregate` (division / compensated
  sum), which was not observed to drift; if a continuous-mean point later proves non-portable
  it is a separate, narrowly-scoped follow-up.

This is a public-contract change (interval floats in `RunRecord`/`Scorecard` now carry ≤12
decimals). The two committed goldens are regenerated deterministically to match; no schema key
changes, so the public-surface key snapshots are unaffected.

## Consequences

- CI is portable: the golden artifacts match on any runner.
- Cross-platform baseline comparisons no longer manufacture last-ULP deltas.
- Consumers reading interval bounds see ≤12 decimals; this is a precision floor, not a meaning
  change. Existing tests assert bounds via inequalities / `math.isclose` (tol 1e-9), so the
  rounding is within their tolerance.
