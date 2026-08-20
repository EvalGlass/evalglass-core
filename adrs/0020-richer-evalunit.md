# ADR 0020 — Richer EvalUnit model (step / trajectory / session)

- **Status:** accepted
- **Date:** 2026-05-31
- **Extends:** the M0 core contracts (`UnitKind`, `EvalUnit`, `ScoreBatch`)

## Context

M5b extends evaluation beyond the call-level MVP to step / trajectory / session
units (P5; build contract §6/§9; EG-M5-5). The `UnitKind` enum already declares
`CALL/STEP/TRAJECTORY/SESSION`, with the last three reserved. A richer unit must
name the sub-units it aggregates over, an aggregate evaluator must be able to emit
a grouped result, and **none of this may change the call-level path or leak a raw
trace shape** (the core stays effect-free and vendor-neutral). This is the one
core-touching M5 change, so it lands isolated, snapshotted, and additive.

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Sub-unit membership | add `EvalUnit.members: list[str]` (default `[]`) — the ids of the calls/steps a trajectory/session aggregates over | Additive; `locator` (already present) carries any addressing hint. |
| Call-level invariant | a `CALL` unit uses neither `members` nor `locator`, so its serialized dict is **byte-unchanged** | Existing snapshots stay valid; the call-level runner is unaffected. |
| Serialization | `members` is emitted only when non-empty; `from_dict` parses it via `_opt_str_list` (fail-closed: non-list / non-string items → `ContractError`) | Same discipline as every core contract. |
| Aggregate result | the existing `ScoreBatch` (related scores from one evaluator invocation) **is** the aggregate-result contract — no new type | An aggregate evaluator over a trajectory returns a `ScoreBatch`. |
| Raw-shape isolation | unchanged — the core sees only `EvalUnit`/`Example`; raw/async trace shapes stay in the `TraceSource` adapters/lane | Build contract §6 trace rule. |

## Consequences

- Trajectory/session evaluation builds on the existing `EvalUnit`/`Example`/`ScoreBatch`
  contracts with one additive field; no new core meaning and no new core type.
- The call-level MVP is provably unaffected (a `CALL` unit's JSON is unchanged; the
  M0/M1 contract snapshots and the call-level runner stay green).
- An aggregate evaluator emits a `ScoreBatch`; non-scored states (missing/partial
  sub-units) follow the normal score-status rules (`non_evaluable`/`blocked`), never `0.0`.
- The harness unit selector (S1b) and the async-observation lane (S1c) build on this
  without further core changes.

## Alternatives considered

- **A new `TrajectoryUnit`/`SessionUnit` type.** Rejected — it would fork the unit
  contract and the evaluator protocol; one `EvalUnit` with `kind` + `members` keeps the
  spine single and the call-level path untouched.
- **A new aggregate-score type.** Rejected — `ScoreBatch` already groups related scores
  from one evaluator; reusing it avoids a parallel contract.
- **Embed sub-unit objects (not ids) in `members`.** Rejected — it would duplicate
  `Example`/`Score` data and bloat the unit; ids reference the sub-units already recorded.
