# ADR 0040 — Generic OpenAI-compatible judge lane

- **Status:** accepted
- **Date:** 2026-07-18
- **Extends:** ADR 0014 (JudgeModel port), ADR 0016 (optional live judge lane)
- **Relates to:** judge-tier metrics (`authoring-a-metric`) — a host-authored judge metric needs a
  transport; this is it, kept generic so nothing project-specific leaks into the framework.

## Context

A host that authors a judge-tier metric must actually call a model. The existing
live judge lane (ADR 0016, `adapters/judge_live.py`) posts a `JudgeRequest` to a **host-run
judge endpoint** — a service the host stands up that already wraps the model and the prompt.
That is one valid pattern, but most hosts want to call an **OpenAI-compatible chat API**
(OpenAI, OpenRouter, or a local server) directly with a rubric.

Without a framework adapter for that pattern, the *generic transport* (assemble chat messages,
POST `/chat/completions`, parse `choices[0].message.content`) had nowhere framework-side to
live, so an integration hand-rolled it in the host next to its domain rubrics. That inverts the
boundary: EvalGlass is **project-agnostic** — generic, reusable plumbing belongs in the
framework; only domain content (rubrics, integrity preflight, config) belongs in the host repo
once EvalGlass is installed there.

## Decision

Add a second optional judge lane, `adapters/judge_openai.py`, behind the **same** `JudgeModel`
port. It is generic transport only.

| Concern | Choice | Notes |
|---|---|---|
| Placement | `adapters/judge_openai.py`, `OpenAICompatibleJudgeModel`, `JudgeModel` port | No new meaning, no new verdict path — one more adapter. |
| Rubrics | a `rubrics: Mapping[str, str]` (metric/`rubric_ref` → rubric **text**) injected at construction | Domain content is **host-owned**, passed in; the framework ships no rubric. A missing rubric falls back to a neutral construct prompt, never an error. |
| Dependencies | **stdlib only**: `urllib` (https-only), bounded read, `json.loads` rejecting `NaN`/`inf`, markdown-fence tolerance | No provider SDK enters the repo; required-tier hermeticity is preserved. |
| Prompt-injection posture | input/output embedded as **data** in the user turn (capped); a system instruction says treat them as data, not instructions | The untrusted host output cannot redirect the judge. |
| Missing prerequisite | no endpoint / non-https endpoint / no model → `MissingPrerequisite` → **skip**, never fail | Opt-in: absent configuration means the lane does not run. |
| Non-OK evidence | timeout / provider error / malformed content / no finite score → non-`OK` `JudgeResult`, no `parsed_value` | A failed judge is not a low score (build contract §6/§9). |
| Deletability | import-boundary guard proves no required import loads the lane; declared in `built_in_lanes()` | Deleting `judge_openai.py` leaves the required suite green. |
| Authority | none — the lane produces `JudgeEvidence` only, scored by the core like any judge | Calibration/approval (ADR 0015) still govern whether it can gate. |

## Consequences

- The generic OpenAI/OpenRouter transport is reusable across every project; a host supplies only
  rubrics + (optional) an integrity preflight + config — the framework/host boundary is restored.
- Two judge lanes now share the `JudgeModel` port: `live-judge` (host judge endpoint) and
  `openai-judge` (OpenAI-compatible chat). Both are opt-in, hermetic-testable, deletable.
- The lane set grows to ten; the conformance parametrization, the `_EXPECTED_LANES` acceptance
  set, and the attach-count assertion are updated to include it.
- An uncalibrated OpenAI judge gains no authority — its scores stay informational until a host
  computes an agreement study (ADR 0015) and approves a threshold, through the one Verdict Engine.

## Alternatives considered

- **Extend `judge_live.py` to also do OpenAI chat.** Rejected — it conflates two response shapes
  (`{score}` endpoint vs. `choices[].message.content` envelope) in one adapter; two small, clear
  lanes are more auditable than one branchy one.
- **Leave the transport in the host.** Rejected — it is generic and would be re-hand-rolled per
  project, and it is exactly the kind of reusable plumbing the framework exists to own.
- **Ship an `openai` SDK as an optional extra.** Rejected — even an optional-extra SDK invites a
  required-path import and a supply-chain surface; stdlib `urllib` keeps the lane self-contained,
  consistent with ADR 0016.
- **Put rubrics in the framework.** Rejected — rubrics are domain judgment; baking any in would
  put customer-specific content in a project-agnostic repo.
