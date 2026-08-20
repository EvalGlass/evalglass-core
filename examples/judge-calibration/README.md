# Example: a judge metric and the calibration prerequisite

A worked example showing how an **LLM-judge metric** behaves honestly: it produces real scores, but
it **cannot gate until the host calibrates it** — even if the config asks it to. This is the
`judge_score` + calibration story from the [`calibrating-a-judge`](../../skills/calibrating-a-judge/SKILL.md)
skill, runnable end to end with **no network and no provider SDK** (the `fake` judge adapter
produces deterministic evidence from each example's `context.judge` directive).

## Run it

```bash
# inside an installed host:
PYTHONPATH=evals python -m _evalglass.harness.cli run --config evals/evalglass.yaml
# from this repo, against the framework source:
cd evals && PYTHONPATH=../../../src python -m evalglass.harness.cli run --config evalglass.yaml
```

## What you get (committed under `evals/reports/judge-calibration/`)

- **`scorecard.json`** / **`runrecord.json`** / **`report.md`** — real artifacts, regenerated from
  the command above (regression fixtures, not hand-edited).
- The `faithfulness` judge metric is **`scored`** for every example (0.9 / 0.7 / 0.6 from the fake
  judge), and its individual scores carry subject identity (`example_id`/`unit_id`) so
  `view --by-call` works.
- The verdict is **`informational`** (`ci_should_fail: false`).

## The point: a judge that is *scored* but cannot *gate*

The config deliberately **tries** to make `faithfulness` gate — `metric_status: gating`, an
`approved` threshold, and a `validated` dataset. It still does not gate: its resolved authority is
`informational` and `can_gate` is `false`. The reason is the missing prerequisite — the judge is
**uncalibrated** (there is no `judge_calibration: calibrated` and no calibration record). EvalGlass
refuses to let an uncalibrated judge decide quality, no matter how good its numbers look.

That refusal is the feature: a green-looking judge number is not a quality claim until a human has
checked the judge against trusted labels.

## How a host would make it gate (the honest path)

1. **Calibrate** — compare the judge's scores to trusted labels and record the result under
   `evals/calibration/` (see `calibrating-a-judge`). Calibration is a host-owned act; nothing here
   self-approves it.
2. **Mark it calibrated** — once calibration evidence exists, the host sets the judge calibrated.
3. **Promote the gate** — then the host activates the gate via host-owned YAML (see
   `promoting-a-gate`). The Verdict Engine — not this config, not the plugin — resolves it.

Until all three hold, the metric stays informational. A `report.md` is a rendering of the typed
`scorecard.json`; read the JSON first.
