# ADR 0057 — Resolve authority from each metric's consumed evidence

**Status:** Accepted

## Context

Authority was resolved run-globally. `runner._run_authority` computed one worst dataset status and
one worst data policy across *every* configured dataset, trace, and enabled trace lane, then fed
that single pair to every metric. With explicit source bindings now available ([ADR 0056](0056-metric-source-bindings.md)),
a metric that consumes only a validated, permitted dataset was still diluted to `proposed` by an
unrelated proposed trace in the same run — precise governance was impossible for mixed-source runs,
and a metric's authority did not describe the evidence it actually consumed.

## Decision

Resolve authority **per metric, over the sources it actually consumes**, while preserving the
run-global worst as the conservative fallback for unbound metrics.

- **`_metric_authority_inputs(metric, config, lane_trace_policies)`** (Harness) computes a metric's
  authority inputs. A **bound** metric (D1 `sources`) resolves dataset status + data policy over
  only its bound sources, across every role — so a bound `reference`/`context`/`observation` source
  counts too, and an unrelated proposed/forbidden source cannot dilute it. An **unbound** metric
  falls back to `_run_authority` (the run-global worst), unchanged.
- **A selector cannot launder a consumed source.** Because the consumed set is the metric's
  *declared* bindings (not its selector-matched subjects), narrowing the population with a selector
  never removes a source from the metric's authority.
- **The worst-of computation is shared, not forked.** `_worst_status` / `_worst_policy` back both the
  global fallback and the per-metric resolution, so bound and unbound paths agree on how a trace
  (never validated gold) or a restrictive policy constrains a source set.
- **Only the core resolver + Verdict Engine decide.** This change selects *which inputs* feed the
  existing `resolve_authority`; the resolution rules, the single Verdict Engine, and the exit path
  are untouched. `preflight` previews the same per-metric authority the real run resolves, so the
  doctor shows each metric's consumed-source authority and reasons.

## Consequences

- Two metrics in one run resolve authority independently: a metric bound to validated, permitted
  gold can gate while a sibling bound to a proposed dataset stays informational — no cross-source
  dilution and no laundering.
- Judge capability/calibration, threshold approval, and baseline needs remain per-metric on the
  metric itself and are carried through unchanged.
- Backward-compatible: an unbound metric keeps the exact run-global worst behaviour and byte-identical
  artifacts. The per-metric bindings and resolved authority reasons are already persisted (the plan's
  `source_bindings` and the Scorecard's per-metric `authority`), so a report/dashboard can show which
  source constrained a metric without new authority logic in any adapter or renderer.
