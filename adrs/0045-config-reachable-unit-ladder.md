# ADR 0045 — Config-reachable trajectory / session unit ladder

- **Status:** accepted
- **Date:** 2026-07-23
- **Related:** the richer `EvalUnit` (`STEP/TRAJECTORY/SESSION`, `members`) from
  [0020](0020-richer-evalunit.md); the harness selector `select_units`
  (`harness/units.py`) and the `trajectory_shape@1` built-in
  (`core/builtins/trajectory_shape.py`); route convergence `run_config`
  (`harness/runner.py`); the worst-source authority rule ([build contract §2 #9]).

## Context

EvalGlass presents itself as an *agentic-app* evaluator, but a config-driven `evalglass run`
scored **one LLM call at a time**. An agent's quality is rarely visible per call — every
individual call can look fine while the run loops, mis-orders tools, or never reaches the goal.
Grading a **trajectory** (all calls sharing a `trace_id`) or a **session** answers *"did the
whole run succeed?"* instead of *"was call #3 well-formed?"*.

The machinery already existed and was unit-tested, but was **unreachable from a run**:

- `select_units(kind=…)` groups call-level trace units by `trace_id` into one aggregate
  `Example` (`unit.members` = the sub-unit ids, `output` = the per-member output list), and
  `trajectory_shape@1` scores that aggregate — but **`select_units` had no production caller**.
- `TraceConfig` exposed **no unit field**, and the harness evaluator loader did not register
  `trajectory_shape`, so a host physically could not request an aggregate run.

`test_m5b_richer_units_proof.py` proved the aggregate path by calling `select_units` directly;
it did not prove config-reachability through `run_config`. This ADR records the decision to
close exactly that gap.

## Decision

Make the trajectory/session ladder reachable from a `traces:` config, converging through the
existing `TraceEnvelope → EvalUnit → Example` path — no new score meaning, no second verdict
path.

1. **Config schema (additive, fail-closed).** `TraceConfig` gains `kind: UnitKind =
   UnitKind.CALL` (YAML key `unit`), parsed with the same `_coerce_enum` pattern as
   `format`/`data_policy`. Absent `unit:` ⇒ `CALL`, so every pre-P1 config is byte-identical; a
   present-but-bogus value is a setup error (present-but-malformed ≠ absent). All four
   `UnitKind` values parse at the config layer.

2. **Evaluator reachability.** `trajectory_shape` is registered in the harness evaluator loader
   so a metric may declare `evaluator_ref: trajectory_shape@1`. (It was previously only in the
   Core `BUILTINS` registry, which `run_config` does not consult.)

3. **Runner wiring + egress of an aggregate (the one hard part).** The runner tracks each
   Example paired with a per-unit egress bool; `select_units` collapses N members → 1 and returns
   bare Examples, dropping that bool. A single helper `_load_trace_units(units, kind)` resolves
   it: `CALL` is the unchanged per-call path; a richer kind resolves the aggregate's egress as
   the **worst of its members** — an aggregate is egress-OK **iff every member is**, so one
   `forbidden`/`unknown`/`missing` member blocks the whole aggregate (fail-closed). This prevents
   a forbidden trace from leaking into a replay/judge egress while still grading the parts that
   are permitted.

4. **Lane-path decision.** The `TRACE_SOURCE` optional-lane path is left **CALL-only**:
   `LaneConfig` carries no `unit:` field, so aggregate grading is reachable through the built-in
   `traces:` route only (the EG-P1 scope). The lane path reuses `_load_trace_units(units, CALL)`,
   which is byte-identical to its prior inline pairing.

5. **`MetricSpec.granularity` decision.** `MetricSpec.granularity` is *also* a `UnitKind` but is
   **not** used to drive selection. The trace-level `unit:` is authoritative for *which aggregate
   is built*; a metric whose `granularity` disagrees with the produced unit is still applied and
   **guards itself** — `trajectory_shape` returns `non_evaluable` (its `not_aggregate` guard) on a
   `CALL` unit, never a fabricated value. The guard fails closed, so no diagnostic-only path is
   needed.

6. **Honesty guard on degenerate aggregates.** `trajectory_shape` now returns `non_evaluable`
   (code `output_all_null`) when **no** member produced an output, instead of `0/N = 0.0`.
   Reporting `0.0` for a trajectory with no output evidence would read as "0% complete quality"
   when the honest state is "no evidence" — the exact `0.0`-collapse the framework forbids.

## Consequences

- A `traces:` block with `unit: trajectory` (or `session`) drives an aggregate run through
  `run_config` end-to-end; `trajectory_shape@1` scores the aggregate; `scorecard.json` and
  `runrecord.json` carry one aggregate row per trajectory with `unit_id = "<kind>:<trace_id>"`.
- **No false confidence.** Traces carry no validated gold, so an aggregate run inherits
  `PROPOSED` dataset status and resolves `informational` — it cannot gate. An approved gating
  threshold over proposed trace data does not activate a gate (it stays `informational`, never a
  laundered pass). An aggregate green is *one shape metric over recorded behavior*, never proof
  the agent succeeded.
- **CALL path unchanged.** Absent `unit:` leaves the parsed config, the per-call Examples, and
  the run fingerprint byte-identical; the config fingerprint changes only when `unit:` is set
  (the aggregate example ids drive it).
- **Scope deliberately held.** No new process metrics (tool-selection, step-order, recovery) —
  those stay host-owned per "generic by contract". No richer per-member evidence contract on
  `EvidenceBundle`. `STEP` groups by `trace_id` like `TRAJECTORY` (its locator semantics beyond
  simple grouping are out of scope). Cross-file grouping is per-read: the same `trace_id` split
  across two trace files yields two aggregates.
