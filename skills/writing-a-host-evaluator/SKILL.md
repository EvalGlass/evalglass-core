---
name: writing-a-host-evaluator
user-invocable: false
description: >-
  How to author a host-owned EvalGlass evaluator (custom domain logic). Use when a built-in metric
  is not enough and the host needs its own scorer. The evaluator returns typed Score or ScoreBatch,
  represents blocked/non-evaluable/error states with status and diagnostics (never 0.0), lives in a
  host-owned path outside evals/_evalglass/, and imports only the vendored _evalglass.core
  contracts — never the framework package or the plugin, so the runtime stays independent.
---

# Writing a host evaluator

Use this when no built-in metric fits and the host needs **domain-specific** scoring. A host
evaluator is **host-owned truth**: it lives outside the managed runtime (e.g.
`evals/evaluators/my_metric.py`), and `evals/_evalglass/` is never edited by hand.

## The contract

An evaluator is a function `evaluate(example, context, evidence) -> Score | ScoreBatch`:

```python
from _evalglass.core import Score, ScoreStatus, Validity, Diagnostic, Severity

def evaluate(example, context, evidence):
    out = example.output
    if out is None:                      # nothing to measure → non_evaluable, NOT a 0.0
        return Score(
            metric=context.spec.name, value=None,
            status=ScoreStatus.NON_EVALUABLE, validity=Validity.NOT_MEASURED,
            evaluator_version="my_metric@1",
            diagnostics=[Diagnostic(code="my_metric.no_output", severity=Severity.ERROR,
                                    message="example carried no output to score")],
        )
    return Score(metric=context.spec.name, value=1.0 if ok(out) else 0.0,
                 status=ScoreStatus.SCORED, validity=Validity.VALID,
                 evaluator_version="my_metric@1")
```

## Rules that keep it honest

- **Import only `_evalglass.core`** (the vendored contracts). Never import the framework `evalglass`
  package, the plugin, or anything under the plugin tree — host code must keep working after the
  plugin and the agent are removed.
- **A non-scored state is never `0.0`.** `blocked` / `non_evaluable` / `skipped` / `error` carry
  **no value** and a diagnostic that says why. A `0.0` is a real measured score, not a missing one.
- **Return data, not verdicts.** The evaluator never computes authority or a verdict — only the
  Verdict Engine does. Wire the metric with `authoring-a-metric` (it stays `proposed`).
- **Test the non-scored states**, not just the happy path — prove your evaluator emits the right
  status + diagnostic when evidence is missing or malformed.
