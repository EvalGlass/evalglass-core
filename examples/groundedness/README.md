# Example: groundedness (reference metric + non-reference floor)

A small, hermetic example that shows the **reference-metric prerequisite** honestly: a reference
metric measures the answer against a grounding reference, but it **cannot gate** until a host
validates the gold and approves a threshold. The non-reference checks give real signal with no gold.

## Run it

```bash
cd examples/groundedness/evals
PYTHONPATH=evals python -m _evalglass.harness.cli run --config evalglass.yaml   # in an installed host
# or, from this framework repo (no install):
PYTHONPATH=../../../src python -m evalglass.harness.cli run --config evalglass.yaml
```

## What you get (committed under `evals/reports/groundedness/`)

| Metric | Lens | Result | Why |
|---|---|---|---|
| `set_overlap` | reference | `~0.31`, **informational** | Groundedness-flavoured token overlap with the reference — but the dataset is `proposed`, so it cannot gate. |
| `field_presence` | non-reference | `1.0`, **informational** | The required `answer` field is present — real signal, no gold needed. |
| `structural_shape` | non-reference | `1.0`, **informational** | The output is a well-formed object. |

**Verdict: `informational`** (exit 0). The committed `scorecard.json` / `runrecord.json` /
`report.md` are regression fixtures, regenerated from the command above — not hand-edited.

## Prerequisites to make the reference metric *gate*

This is the honest part. To turn `set_overlap` into a gate, the **host** must:

1. Replace `datasets/grounded.jsonl` with validated grounding gold and set its `status: validated`.
2. Establish variance over several runs, then set and **approve** a threshold in `authority.json`.

Until then it stays informational — evidence, not a quality verdict.
