# ADR 0059 — Persist the typed paired comparison as primary truth

**Status:** Accepted

## Context

The item-paired comparison math existed (`core.comparison.paired_comparison`, Student-t interval,
interval-licensed improvement/regression), but its only consumer was the drift watcher, which wrote
a `drift.json` **sidecar**. A normal `run` persisted no comparison at all — a report wanting to show
"did quality change" had to either read the sidecar or subtract two aggregate points, which is
dishonest across non-comparable runs and ignores per-item pairing. There was no single typed carrier
of change on the primary artifact, and the HTML report still accepted a raw `previous_values`
mapping and rendered a point-difference that looks like a regression even when the runs are not
comparable.

## Decision

Introduce a typed **`ComparisonResult`** (core contract, `core/comparison.py`) and make it the
primary, and only, carrier of honest change.

- **One typed object.** `ComparisonResult` carries the `purpose` (`promoted_baseline`; a
  `previous_verified` purpose is future work), the comparability `state` (reusing `BaselineState`:
  `comparable` / `not_comparable` / `missing_baseline` / `comparison_not_requested`), the baseline
  run id, the changed fingerprint dimensions (for `not_comparable`), and — **only when
  `comparable`** — the per-metric `PairedComparison`. Its `__post_init__` fails closed on a
  state/delta contradiction (a comparable state must carry deltas; any other must not).
- **A numeric delta is licensed only by a comparable state.** A `not_comparable` run records the
  changed dimensions and no delta; missing / not-requested carry neither. `MetricDelta` gains a
  `direction_adjusted_delta` — the raw delta re-signed so positive always means improvement — the
  value a renderer shows, while the raw delta is retained. Pairing is by shared stable `example_id`,
  never list position; an interval crossing zero is `within_noise`; a single pair is `unresolved`.
- **Built from the verified baseline, in the Harness.** `run_config` loads the full promoted baseline
  RunRecord, passes its fingerprint to the core (which resolves comparability), and after the core
  returns builds the `ComparisonResult` from the baseline's scores + the resolved state via a single
  `build_comparison`. It is attached to the Scorecard; present only when a baseline was configured,
  so a run without one stays byte-identical.
- **One comparison, no fork.** The drift watcher (`harness/drift.py`) now delegates to the same
  `build_comparison` and projects the result into its `DriftResult`/`drift.json` view, so `watch`
  and `run` cannot diverge in comparison semantics. `drift.json` remains readable (a compatibility
  rendering derived from the primary contract).
- **Evidence, not a verdict.** `ComparisonResult` carries no `ci_should_fail` and sets no exit code:
  a regression that should fail CI flows through the single Verdict Engine on a comparable baseline,
  never through this object. The persisted comparison's `state` must equal the Scorecard's own
  `baseline_state` (anti-tamper), and any edit to the persisted values is caught by the run
  manifest/completion-marker integrity.

## Consequences

- Every renderer reads one typed comparison; the Markdown report renders a Comparison section from it
  (a delta only when comparable, else the changed dimensions). The raw-point HTML `previous_values`
  delta path is **deprecated** and will be removed when the diagnostic dashboard lands (Epic E) — it
  is the last place a delta is computed from untyped previous values.
- Additive and backward-compatible: `comparison` is emitted only when computed, `drift.json` keeps
  its shape (and still loads a legacy delta without `direction_adjusted_delta`), and a run with no
  baseline is byte-identical.
