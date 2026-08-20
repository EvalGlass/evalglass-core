# ADR 0016 — Optional live judge provider lane

- **Status:** accepted
- **Date:** 2026-05-31
- **Extends:** ADR 0014 (JudgeModel port)

## Context

The required tier proves the judge contract against fake deterministic evidence
(ADR 0014), but a host eventually wants to score with a real provider. A live lane
is useful only if it never becomes a required dependency and never pollutes the
hermetic required tier (`CLAUDE.md §14`; build contract §M4/§M5). Optional lanes
are the M5 theme; the live judge is the first one and sets the pattern.

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Placement | `adapters/judge_live.py` behind the **same** `JudgeModel` port | No new meaning, no new verdict path — it is one more adapter. |
| Dependencies | **stdlib only**: `urllib` (https-only), bounded response read, `json.loads` rejecting `NaN`/`inf` | No provider SDK enters the repo; required-tier hermeticity (ADR 0014) is preserved. |
| Missing prerequisite | no endpoint/credentials → `MissingPrerequisite` → **skip**, never fail a required path | Opt-in: absent configuration means the lane simply does not run. |
| Deletability | tests use `pytest.importorskip`; an import-boundary guard proves no required import loads the lane | Deleting `judge_live.py` leaves the required tests green. |
| Authority | none — the lane only produces `JudgeEvidence`, scored by the core like any judge | Calibration/approval (ADR 0015) still govern whether it can gate. |

## Consequences

- Live judging is opt-in and removable; the required tier never imports it, so a
  required run stays hermetic and offline.
- A missing endpoint or credential is a skip, not a failure — the lane cannot break
  a host that has not opted in.
- Deletion is verified: removing the lane changes no required output, which is the
  reusable acceptance pattern for every M5 optional lane.
- A live judge gains no special authority; only a calibrated metric with an approved
  threshold gates, through the single Verdict Engine.

## Alternatives considered

- **A provider SDK (e.g. an `openai` client) in the live adapter.** Rejected —
  even an optional-extra SDK invites a required-path import and a supply-chain
  surface; stdlib `urllib` keeps the lane self-contained and auditable.
- **Make the live lane the default judge.** Rejected — it would make every run
  depend on a live service and break local-first CI.
- **Skip the deletion guard.** Rejected — without it, "optional" is a claim, not a
  proven property; the guard is what makes the lane honestly deletable.
