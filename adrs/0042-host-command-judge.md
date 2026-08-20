# ADR 0042 — Host command judge (subprocess JudgeModel)

- **Status:** accepted
- **Date:** 2026-07-19
- **Extends:** ADR 0014 (JudgeModel port), ADR 0007 (subprocess TaskRunner)
- **Relates to:** ADR 0016 / ADR 0040 (opt-in judge lanes), ADR 0015 (calibration authority)

## Context

teta's config-driven run (`harness/runner.py:run_config`, behind `evalglass run`) collected judge
evidence with the **fake** judge only. The opt-in `JUDGE_MODEL` lanes (`live-judge`, `openai-judge`)
are recorded *skipped* pre-core — their evidence integration is a deferred follow-up. So a host
that declared a judge metric could **not run a real judge inside a config-driven eval**; it had to
hand-roll a bespoke run script that pre-computed judge scores outside the harness (as early field
integrations had to).

The predecessor framework (beta) had already solved this with a **command judge**: a host-owned
subprocess declared in config (`judge: command`, `judge_command: [...]`) that reads
`{input, output, rubric}` on stdin and writes `{value, rationale}` on stdout. It is the judge
analogue of the M2 subprocess **task runner** (ADR 0007) — an effect the harness owns, over a
JSON contract, with the argv as the whole trust surface.

## Decision

Add a **`SubprocessJudgeModel`** (`adapters/judge_subprocess.py`) and wire it into `run_config`.

| Concern | Choice |
|---|---|
| Contract | Child process over JSON: stdin `{example_id, metric, input, output, reference, rubric}` → stdout `{"value"\|"score": 0..1, "rationale"}`. `shell=False`; host argv is the trust surface. |
| Config | `judge: {adapter: command, command: [...argv], timeout_seconds: N}`. `fake` stays the default; an unknown/under-specified adapter is a setup error. |
| Rubric | The adapter reads the host rubric from the **path-contained** `rubric_ref` under the evals root and passes its text in stdin — so one judge script serves many rubrics (a path escape fails closed). |
| Failure modes | spawn failure / non-zero exit → `PROVIDER_ERROR`; timeout → `TIMEOUT`; malformed / non-finite / missing score → `MALFORMED`. Non-`OK` carries **no value** — a failed judge is never a low score. |
| Data policy | Egress is enforced **upstream** in `collect_judge_evidence` (a forbidden source is never sent to any judge), exactly like replay — the command judge inherits it. |
| Authority | The judge stays **uncalibrated → informational** until a host computes an agreement study (ADR 0015). Running a real judge changes no verdict on its own. |
| Home | The host judge lives in `evals/judges/<name>.py` — the host-owned-truth location the canonical layout previously lacked. |

## Consequences

- A host can run a **real judge inside `evalglass run`** — no bespoke run script — closing a
  capability regression versus beta with a lower-blast-radius change than wiring the deferred
  `JUDGE_MODEL` lanes into core scoring (the fake-judge hermetic gating is untouched; the command
  judge is opt-in and effectful, like the task runner).
- `evals/judges/` becomes a recognized host-owned-truth directory (host judge subprocess),
  alongside `rubrics/` (its rubric) and `calibration/` (its agreement study).
- The `openai-judge` lane (ADR 0040) remains a valid *generic transport* for hosts that prefer an
  OpenAI-compatible endpoint; the command judge is the path for **arbitrary host judge logic**
  (domain preflight, provider choice, prompt) run inside a config-driven eval.

## Alternatives considered

- **Wire the `JUDGE_MODEL` lanes into `collect_judge_evidence`.** Rejected for now — higher blast
  radius (it touches the hermetic fake-judge gating coverage and needs the M4 acceptance-pack
  rework the M7 docs flagged); the command judge delivers the same host-judge capability through
  the established effectful-subprocess seam.
- **Thread the rubric text through `JudgeRequest`/`RubricRef`.** Rejected — the adapter reading the
  already-validated, path-contained `rubric_ref` keeps the change local (no core/port contract
  change) and mirrors how the task runner reads under the root.
- **A shell command string instead of an argv list.** Rejected — `shell=True` would let host data
  be interpreted as a command; argv + `shell=False` keeps the trust surface explicit (ADR 0007).
