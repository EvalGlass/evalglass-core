# ADR 0047 — Diagnostic clusters in the Scorecard

- **Status:** accepted
- **Date:** 2026-07-23
- **Related:** the anti-tamper load recompute ([0038](0038-m7-epistemic-core-tranche.md) G5); the
  additive-field convention (`estimates`/`claim_specs` on the `Scorecard`); the harness explorer's
  call-identity grouping ([0024](0024-score-subject-identity.md)); the per-source-function non-goal
  ([0037](0037-per-source-function-view-not-built.md)).

## Context

A metric that reports `faithfulness = 0.82` says *that* something is wrong, not *what*. The useful
question is *"which 18% failed, and do they share a cause?"* — e.g. *"all failures are
missing-citation cases."* Grouping failing/non-scored items by their shared **diagnostic** turns a
flat number into an **actionable failure mode**.

teta had **no runtime clustering**: the only grouping construct was a static, authored one that
never executes in a run. The public site meanwhile shows a "Missing-citation cluster" row as if it
exists. This ADR builds the honest, effect-free data layer under that claim.

Two things it is **not**: it is not the harness explorer (which groups scores by *call identity* —
`example_id`/`unit_id`), and it is not per-source-function grouping (a fenced non-goal, ADR 0037).
It is a *different axis*: failure **instances by cause**.

## Decision

1. **Cluster key = `Diagnostic.code`.** A pure, effect-free, stdlib-only function
   `cluster(scores) -> list[DiagnosticCluster]` (in `core/clusters.py`) groups the run's `Score`s by
   `(metric, diagnostic.code)`. Each score contributes **once** per code (duplicate codes on one
   score count the item once). A `DiagnosticCluster` carries `metric`, `code`, `severity`, `count`,
   and a representative `message` — **no value**. A `blocked`/`non_evaluable`/`error` item is grouped
   by its code and counted, **never** coerced to a `0.0` value (CLAUDE.md §9).

2. **Order-invariant, canonically sorted.** The result is sorted by (severity desc, count desc,
   metric, code), so two runs over the same scores in any order produce an **equal** list. This is
   what lets the Scorecard store the clusters while the anti-tamper check recomputes them.

3. **Additive Scorecard field, recompute-safe.** `Scorecard.clusters` is emitted only when
   non-empty (a pre-P3 `scorecard.json` is **byte-identical**), parsed absent→`[]`. The engine
   computes it from `all_scores` when composing the Scorecard. **`_verify_consistency` recomputes the
   clusters from the persisted `scores`** and rejects a mismatch (a fabricated or hand-edited cluster
   fails closed exactly like a tampered aggregate). A record with **no** clusters is not checked
   (matching the `estimates` convention): a pre-P3 record whose scores carry diagnostics still loads,
   and dropping the clusters loses explanatory structure only — it manufactures no value, verdict, or
   authority.

4. **Which items is the explorer's axis, not the cluster's.** The cluster deliberately carries **no**
   `example_ids`: it describes the failure *mode* (cause + count + severity). Drill-down to *which*
   items uses `evalglass view --by-call` (the explorer's call-identity grouping). Keeping identity off
   the cluster also makes the recompute robust to a score whose identity is absent (an old artifact).

5. **Facet declaration.** The default (and only) group-by is `Diagnostic.code`; it needs no new
   contract. A first-class `group_by` facet is deliberately **not** added now — `MetricSpec.profile`
   is already free-form if a host later needs an override, and adding one before there is a second
   facet would be speculative. Recorded here so the decision is explicit.

6. **Vocabulary precision.** A runtime cluster groups **failure instances** (which items failed for
   the same reason), keyed by the diagnostic `code`. It is not a grouping of metric *names* into
   quality themes — the two ideas do not share a type, and a cluster is recomputed from the saved
   scores on load so a hand-edited one fails closed.

## Consequences

- A run's failing/non-scored items are grouped by `Diagnostic.code` into a typed, per-metric cluster
  view on the `Scorecard`, computed effect-free from the scores and recomputable on load.
- `report.md` and `report.html` render cluster sub-rows (`<code>: N cases`) from the typed field
  only — no re-grouping, no authority; the no-cluster path is byte-identical to pre-P3.
- **No false confidence:** a cluster view adds explanatory structure only. It never changes a
  verdict, never manufactures authority, and never turns a non-scored state into a `0.0`.
- The site's "failure cluster"-vs-"metrics-explorer-planned" inconsistency is now resolvable on the
  framework side (the site edit is a separate site-repo PR).
