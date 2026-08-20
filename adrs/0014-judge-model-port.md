# ADR 0014 — JudgeModel port and the fake-adapter contract

- **Status:** accepted
- **Date:** 2026-05-31
- **Extends:** ADR 0001 (architecture boundary), ADR 0007 (subprocess TaskRunner — the same failure→typed-evidence discipline)

## Context

M4's exit criterion is *judge metrics can become gating only through calibration
evidence and approved thresholds; judge failures cannot masquerade as low scores*
(build contract §M4; `CLAUDE.md §14`). A judge call is an **effect**, and a judge
response is **evidence**, not authority. Recording the port before code lands
guards three trust hazards:

- **An effect leaking into the core.** If the effect-free core called a judge, it
  would no longer be stdlib-only and deterministic (`CLAUDE.md §8`).
- **A non-hermetic required tier.** If the required path reached the network or
  imported a provider SDK, every required run would depend on a live service —
  the opposite of local-first (build contract §3).
- **A judge failure becoming a quality score.** A timeout or malformed response
  rendered as `0.0`/`pass` is false confidence: missing measurement read as bad
  quality (`CLAUDE.md §9`).

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Port | `harness/ports.py` `JudgeModel` Protocol: `judge(JudgeRequest) -> JudgeResult` | A visible effect boundary, owned by the Runtime Harness. |
| Envelopes | `JudgeRequest` (example/metric/context/rubric refs) and `JudgeResult` (status, raw/parsed value, rationale, token/cost/latency, diagnostics) | Carry evidence/data only — never a `Score`, authority, or verdict. |
| Required-tier adapter | `adapters/judge_fake.py` `FakeJudgeModel`: deterministic, no network, no SDK; driven by a per-example `context["judge"]` directive; carries a call **ledger** | The only judge in the required tier; live providers are a separate optional lane (ADR 0016). |
| Failure handling | timeout · empty · malformed · provider-error · missing → typed `Diagnostic` + **no parsed value** | Mirrors the M2 subprocess failure discipline (ADR 0007); never a fabricated value. |
| Collection | `harness/judge.py` `collect_judge_evidence` runs **after** the data-policy egress guard | A forbidden/missing-policy example spawns **no** call (the ledger proves it) → `MISSING` evidence → the gate blocks. |
| Absent calibration | a judge metric with no host calibration record resolves `UNCALIBRATED` | Closes the hole where a bare config field would let a judge gate uncalibrated (see ADR 0015). |
| Core role | the effect-free `judge_score` evaluator only **parses** `evidence.judge_evidence` into a `Score` | The core never calls a judge; meaning stays in the core, effects in the harness. |

## Consequences

- Judge calls live only in the Runtime Harness; the required tier imports no
  provider SDK and makes no network call — enforced by the EGTS no-network/no-SDK
  checker and `tools/check_core_isolation.py`.
- A judge failure becomes a typed diagnostic and a `blocked`/`non_evaluable`/`error`
  state (ADR 0015 / `CLAUDE.md §9`), never a `0.0` — an infrastructure failure
  stays distinguishable from a low-quality answer.
- Data policy is enforced before the effect, so policy-forbidden data is never sent
  to a judge.
- A live provider attaches through the **same** port as an isolated, deletable lane
  (ADR 0016); the required contract is proven against fake evidence first.

## Alternatives considered

- **Let the core evaluator call the judge directly.** Rejected — it makes the core
  effectful and non-deterministic, and couples score meaning to a live service.
- **Return a `Score` from the adapter.** Rejected — the adapter would manufacture
  authority; only the core turns evidence into a `Score`, and only a calibrated,
  approved metric can gate (ADR 0015).
- **Use a real provider in the required tier behind a flag.** Rejected — any
  required-path SDK import breaks the hermetic guarantee; the fake adapter is the
  required tier, the live lane is opt-in (ADR 0016).
