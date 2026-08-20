# EvalGlass quickstart

A small, honest, fully local run — no network, no API keys, no services. It exercises both
input routes (a JSONL **dataset** and a local **trace**), four metrics (a reference metric, two
deterministic non-reference built-ins, and one **host-owned** evaluator), and produces the
primary machine artifacts plus a Markdown report.

## Run it

From this `quickstart/` directory:

```bash
evalglass run --config evals/evalglass.yaml
```

(Equivalently, from the framework repo without installing the console script:
`python -m evalglass.harness.cli run --config examples/quickstart/evals/evalglass.yaml`.)

## What you get

The run prints a terminal summary and writes, under `evals/reports/quickstart/`:

| File | What it is |
|---|---|
| `runrecord.json` | The complete, machine-readable record (config, scores, provenance, verdict). |
| `scorecard.json` | The compact authority-aware summary (the primary contract). |
| `report.md` | A human-readable rendering of `scorecard.json`. |

The exit code comes only from the core verdict: `0` for pass/informational, `1` for
fail/blocked, `2` for a setup error (bad config, missing file, …).

## This run is INFORMATIONAL — and that is the point

The terminal summary and report say **informational**, and the process exits `0`. That does
**not** mean "quality verified". It means *no metric is authorized to gate yet*:

- the dataset is `proposed` sample gold, not validated domain truth;
- no threshold is `approved`;
- (judges, added in M4, would also need calibration).

A green informational run is **evidence, not proof**. EvalGlass refuses to imply more authority
than the run actually has.

## Make a metric gate (only after you validate)

Gating is an explicit, host-supplied act. In `evals/evalglass.yaml`, once a domain expert has
confirmed the gold and chosen a threshold, a metric can be promoted:

```yaml
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: datasets/arithmetic.jsonl
    metric_status: gating       # ask the Verdict Engine to gate on it …
    threshold_approval: approved # … with an approved threshold …
    threshold: 0.9              # … at this value.
```

mark the dataset validated:

```yaml
datasets:
  - path: datasets/arithmetic.jsonl
    status: validated
    data_policy: permitted
```

and **remove the `traces:` block for the gating run**. EvalGlass scores every metric over
*every* configured source and resolves authority to the worst source; a trace carries no
validated gold, so any trace in the config keeps the metric `proposed` (informational) and it
cannot gate. Gate on a dataset-only config — keep a separate informational config if you still
want to look at traces.

With the dataset validated, the threshold approved, and no diluting source, the metric can
`pass`/`fail` in CI. Until every one of those is in place, it stays informational — by design.

## Add your own evaluator

`evals/evaluators/answer_nonempty.py` is a host-owned evaluator: a deterministic
`(example, context, evidence) -> Score`. Copy it, change the logic, and reference it from a
metric as `evaluator_ref: evaluators/<your_file>.py:evaluate`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `setup error [config_not_found]` | `--config` path is wrong. |
| `setup error [config_invalid]` | The YAML parsed but violates the schema (e.g. no `metrics`). |
| `setup error [dataset_not_found]` | A `datasets:`/`traces:` path doesn't exist relative to the config dir. |
| `setup error [evaluator_unknown]` | An `evaluator_ref` names no built-in and no `path.py:function`. |
| Verdict is `blocked` | An active gate can't make an honest claim (e.g. a malformed record, or a regression gate with no comparable baseline). |
