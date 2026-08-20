# ADR 0050 — EvaluationPlan as a persisted, plan-before-effects execution contract

**Status:** Accepted

## Context

EvalGlass has typed per-metric selectors (ADR 0049) and per-source data-policy egress checks, but
they were resolved *late* and in *two places*. Judge-evidence collection iterated the Cartesian
product of every judge metric and every example, and the selector was applied afterwards inside the
pure core scorer (`_collect`). Task replay ran for every output-less example regardless of whether
any metric consumed it. Consequences, confirmed by two field evaluations of a real
LangGraph/LiteLLM/Temporal app:

- a host judge had to re-implement the selector to short-circuit irrelevant pairs (duplicated
  applicability truth);
- a developer could not see, before running, how many external (judge) requests a run would make,
  which examples were eligible, or why examples were excluded — so cost and egress were invisible
  until execution;
- the population that produced scores and the population that produced judge evidence could, in
  principle, diverge.

This work requires one applicability/effect plan resolved **before any effect**, consumed by
scoring, judge collection, replay, `preflight`, and dry-run, with the executed run reconciled against
it.

## Decision

Introduce a typed, JSON-serialisable **`EvaluationPlan`** (Harness-owned, `harness/plan.py`) and a
pure `build_plan()` that projects, over the loaded `(Example, egress_ok)` subjects and the effective
metrics:

- one `PlannedSubject` per loaded example instance, with a **stable plan-local `subject_id`**
  (`s0`, `s1`, …) assigned by load order — unique even when host `example_id` values collide;
- one `PlannedMetric` per configured metric — its selector, unit kind, and a **reconciled population
  ledger** (available / selector-matched / eligible / per-reason excluded);
- one `PlannedEffect` per eligible judge or replay effect, keyed by a **stable effect id**
  (`judge:<metric>:<subject>`, `replay:<subject>`), carrying its fail-closed policy decision,
  instrument reference, and request fingerprint.

`run_config` resolves the plan once (via `preflight()`) and drives effects from it:

- `collect_judge_evidence` iterates `plan.judge_effects()` — the Cartesian product is gone; a
  selector-mismatched or integrity subject never builds a request;
- `_replay_missing` runs only for the plan's replay subjects;
- planned vs handled effects are reconciled into typed `PlanDeviation`s and persisted on a new
  additive `RunRecord.plan` field (digest + planned/handled/deviated counts + deviations).

New side-effect-free CLI surface: `evalglass preflight` and `evalglass run --dry-run`, both projecting
the same plan and writing a versioned, fingerprint-verified `run-plan.json`.

### Ownership and boundaries

- **Planning belongs to the Harness.** The planner is effect-free (no network, subprocess,
  clock-dependent id generation, scoring, authority resolution, or verdict) but consumes host config
  and loaded examples, so it lives in the Harness, not the effect-free core.
- **The core stays untouched by the plan.** `RunRecord.plan` is a plain JSON mapping validated like
  `lane_results`; the core never imports the Harness plan model. It records *evidence of execution*,
  never authority, and is deliberately **not** on `Scorecard`, so verdict/CI/exit stay plan-free.
- **One selector implementation.** Applicability is decided only by `ExampleSelector.matches`
  (ADR 0049); the plan does not re-implement the grammar.

## Honesty rules (fail-closed)

1. Planning grants no authority and makes no verdict.
2. A policy-denied effect is handled as typed `MISSING`/deviation evidence, never a numeric zero.
3. An executed effect absent from the plan is an integrity failure — it forces the run-integrity
   (route-error) block so an active gate cannot pass over it.
4. A run-integrity subject bypasses every selector (it must still reach an active gate) but causes
   no external judge egress.
5. The plan fingerprint moves for score-determining changes (selector, source, policy, instrument,
   evidence) and is stable for cosmetic ones (the `run_id` label).
6. `preflight`/`--dry-run` perform no provider call, judge call, task replay, baseline promotion, or
   authority mutation; missing credentials are named by environment variable only; cost is an
   upper-bound estimate, never an invoice.

## Compatibility

Purely additive. A config with no selectors matches every subject, so judge and replay call counts
are identical to the pre-plan runner. `RunRecord.plan` and `run-plan.json` are new; a pre-plan
`RunRecord` (no `plan` field) still loads. The judge-collection signature changed
(`collect_judge_evidence` now takes the plan); this is internal to the Harness.

## Consequences

- Judge requests are bounded to eligible pairs — no wasted provider egress on mismatched subjects.
- Cost, egress, and eligibility are visible before execution via `preflight`/`--dry-run`.
- The scored population and the judge/replay population cannot diverge — both derive from one plan.
- New public artifacts to version going forward: `evalglass.evaluation-plan/1` and
  `evalglass.preflight/1`.

## Alternatives considered

- **Plan model in the effect-free core.** Rejected: the plan needs loaded examples and config, which
  are Harness concerns; putting it in core would either pull effects into core or force the core to
  import Harness config.
- **Embed the full plan in every `RunRecord`.** Rejected as bloat; the reconciliation digest +
  counts + deviations are sufficient on the record, and the full plan is the `run-plan.json` /
  preflight artifact.
- **Keep the Cartesian judge loop and filter inside the collector.** Rejected: it keeps two
  applicability implementations and still serialises mismatched subjects into requests.
