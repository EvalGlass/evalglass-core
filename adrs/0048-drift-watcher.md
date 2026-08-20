# ADR 0048 — Continuous drift watcher

- **Status:** accepted
- **Date:** 2026-07-23
- **Related:** paired baseline deltas + interval licensing (`core/comparison.py`, part of the M7
  tranche [0038](0038-m7-epistemic-core-tranche.md)); comparability state (`core/provenance.py`);
  the baseline file + explicit promotion ([0009](0009-baseline-file-and-promotion.md)); the
  lane-attach seam's "evidence, not authority" `LaneResult` shape ([0031](0031-runner-attach-seam-and-lane-results.md)).

## Context

Quality doesn't fail at one moment — it *erodes*: a provider silently updates, a prompt tweak lands,
retrieval degrades, and you find out weeks later from a user. teta could answer *"is it worse than
baseline?"* **only when a human manually ran a comparison.** The site's `/use-cases/drift` says a
watcher is "planned, not shipped."

All the ingredients existed — baseline persistence, paired deltas with interval-licensed labels
(`core/comparison.py`), comparability state — but **`comparison.py` had no production caller** (only
its unit tests used it). This ADR records its first consumer.

## Decision

Add an opt-in **drift watcher** that re-runs, compares to baseline, and flags drift honestly, under
two hard invariants.

1. **"Continuous" = scheduled re-invocation, not a daemon.** `evalglass watch --config <yaml>` runs
   **one** drift cycle (run → load baseline → compare → persist → summarize) and **exits**. The
   cadence is external (a nightly cron or a CI job). This keeps effects bounded, stays
   hermetic-testable, and fits the local-first identity — no resident process, no hosted monitor.

2. **The drift evaluation is a harness consumer of a Core function.** `harness/drift.py`
   `evaluate_drift(current, baseline, directions)` feeds the two runs' scores into the Core's
   `paired_comparison` and returns a typed `DriftResult`. The interval-licensing rule (`_classify`)
   is **reused, never re-implemented**: a `regression` label is licensed **only** when the runs are
   `comparable` (`BaselineState.COMPARABLE`) **and** the paired interval clears zero; a delta inside
   the interval is `within_noise`; `not_comparable`/`missing_baseline` is reported as exactly that,
   never as "no regression". A metric with no declared direction is *skipped* (recorded), never a
   crash.

3. **No second verdict path (hard).** `DriftResult` carries **no** verdict, exit class, or authority
   (mirroring `LaneResult`). Drift surfaces as a typed `drift.json` artifact plus an explanatory
   `Diagnostic` (INFO/WARNING) appended to the Scorecard *after* the verdict — the verdict, authority,
   scores, and clusters are unchanged. The exit code still derives **only** from the run's
   `VerdictPayload`. If a regression *should* fail CI, that already flows through the Verdict Engine on
   a `comparable` baseline with an approved gate — not through a new drift exit.

4. **The watcher never auto-promotes the baseline.** It **reads** the baseline (the full promoted
   `RunRecord`, for the item-paired comparison) and compares; it never writes it. Promotion stays the
   explicit, separate `baseline update` act. Drifting does not move the bar.

5. **`watch` requests comparability when a baseline is configured.** Comparison is off by default in a
   plain `run` (`comparison_requested=false`); since `watch` exists *to* compare, it sets
   `comparison_requested=true` when `baseline_path` is set. This only *enables* the comparison — the
   core still decides `comparable`/`not_comparable` honestly from the fingerprints; it never relaxes
   the licensing rule. A configured baseline whose file is absent (a legitimate first run before any
   promotion) is a graceful `missing_baseline`, not an error; a present-but-malformed baseline is a
   setup error.

## Consequences

- `evalglass watch` runs one honest drift check and exits; scheduling is external (a documented cron
  snippet). The drift artifact (`reports/<run-id>/drift.json`) is written via the result store's
  atomic writer and can be tracked over time.
- **No false confidence:** a "no comparable regression found" result explicitly says *this does not
  mean quality is fine* — only that this comparison found no comparable regression. A `not_comparable`
  state is reported plainly, never laundered into "no regression". Drift never changes a verdict, adds
  no exit class, and never moves the baseline.
- The site's `/use-cases/drift` "watcher planned" copy is now a shipped capability on the framework
  side (the site edit is a separate site-repo PR).
