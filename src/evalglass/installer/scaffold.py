"""Scaffold host-owned assets with safe (informational) defaults (EG-M3-3).

``scaffold`` writes a useful starter set of *host-owned* truth under ``evals/`` —
a commented config, a runnable sample dataset/trace, a host evaluator template, an
empty approval ledger, and a README — so a fresh install does something out of the
box. Everything is **informational by construction**: every metric defaults to
``informational`` with a ``proposed`` threshold (the M1 config loader's authority-safe
defaults), the dataset is ``proposed``, and the ``AuthorityRecord`` is empty — so a
first run is informational, never a silent gate (P8/P15; build contract §2 #9).

Scaffolding **never overwrites** an existing host file (host-owned truth is preserved;
an existing file is reported as preserved, not created). Host evaluators live outside
the managed ``_evalglass/`` tree and import the vendored runtime namespace.
This is integration-time code; the runtime never imports it (ADR 0010).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from evalglass.installer.contracts import AuthorityRecord, InstallerError

# --- templates (host-owned starter assets) ----------------------------------

_CONFIG_YAML = """\
# EvalGlass configuration (scaffolded by the EvalGlass skill).
#
# INFORMATIONAL BY DESIGN: no metric here carries gating authority. A green / non-failing
# run of this starter config is NOT proof of quality — the dataset is `proposed` sample
# gold (not validated), no threshold is `approved`, and no judge is calibrated. Granting
# gating authority is an explicit, host-owned act: validate your gold (set the dataset
# `status: validated`), approve a threshold, and set the metric `metric_status: gating`.
# See README.md and authority.json.

run:
  id: scaffold

datasets:
  # status defaults to `proposed` — replace with your validated gold, then set status: validated.
  - path: datasets/sample.jsonl

traces:
  - path: traces/sample.jsonl
    format: local

metrics:
  # Reference metric: did the output equal the gold answer? (runs on the dataset)
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: datasets/sample.jsonl

  # Non-reference structural floor: is the output a well-formed object?
  - name: structural_shape
    evaluator_ref: structural_shape@1
    lens: non_reference
    score_type: binary

  # Non-reference field check (host params): is the `answer` field present?
  - name: field_presence
    evaluator_ref: field_presence@1
    lens: non_reference
    score_type: continuous
    score_range: [0, 1]
    params:
      required_fields: ["answer"]

  # A host-owned evaluator loaded from a local file (see evaluators/answer_nonempty.py).
  - name: answer_nonempty
    evaluator_ref: evaluators/answer_nonempty.py:evaluate
    lens: non_reference
    score_type: binary

output:
  dir: reports
"""

_SAMPLE_DATASET = (
    '{"input": "2+2", "output": {"answer": "4"}, "reference": {"answer": "4"}}\n'
    '{"input": "10-3", "output": {"answer": "7"}, "reference": {"answer": "7"}}\n'
    '{"input": "6*7", "output": {"answer": "42"}, "reference": {"answer": "42"}}\n'
)

_SAMPLE_TRACE = (
    '{"trace_id": "t1", "behavior": {"input": "capital of France?", '
    '"output": {"answer": "Paris"}}}\n'
    '{"trace_id": "t2", "behavior": {"input": "color of the clear sky?", '
    '"output": {"answer": "blue"}}}\n'
)

# Host evaluators run under the *vendored* runtime, so they import `_evalglass.core`
# (the host has no `evalglass` package — only the vendored `_evalglass`).
_EVALUATOR_TEMPLATE = '''\
"""Sample host-owned evaluator (scaffolded by the EvalGlass skill).

Scores 1.0 when the output object carries a non-empty ``answer`` field, else 0.0. Every
host evaluator follows this shape: a deterministic, effect-free
``(example, context, evidence) -> Score``. Copy this file, change the logic for your
domain, and point a metric's ``evaluator_ref`` at ``evaluators/<file>.py:evaluate``.
"""

from __future__ import annotations

from collections.abc import Mapping

from _evalglass.core import EvaluatorContext, EvidenceBundle, Example, Score, ScoreStatus, Validity


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence  # this evaluator needs only the example
    output = example.output
    answered = isinstance(output, Mapping) and bool(output.get("answer"))
    return Score(
        metric=context.spec.name,
        value=1.0 if answered else 0.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="answer_nonempty@1",
    )
'''

_README = """\
# EvalGlass evaluation assets (host-owned)

This directory holds **host-owned truth** — datasets, traces, evaluators, rubrics,
calibration, baselines, and the approval ledger. The managed framework runtime lives
under `_evalglass/` and is replaced on upgrade; everything else here is yours.

## This is informational until you validate it

A fresh run is **informational** — not proof of quality. Before any metric can gate:

- [ ] Validate gold: replace `datasets/sample.jsonl` with real gold and set its
      `status: validated` in `evalglass.yaml`.
- [ ] Approve a threshold: add a `threshold` and set `threshold_approval: approved`.
- [ ] Calibrate judges (if used): record calibration before a judge metric gates.
- [ ] Choose a baseline: promote a run with `evalglass baseline update` for regression gates.
- [ ] Review data policy: declare each dataset/trace `data_policy`.
- [ ] Activate the gate: set the metric `metric_status: gating`.

Record approvals in `authority.json` (empty by default — no authority is granted until you
fill it in). The skill never grants authority for you.

## Run it

From the host repo root (the vendored runtime lives at `evals/_evalglass`, so put `evals`
on the import path):

```
PYTHONPATH=evals python -m _evalglass.harness.cli run --config evals/evalglass.yaml
```
"""

_CI_SNIPPET = """\
# Sample CI workflow for EvalGlass — copy to .github/workflows/ to enable.
#
# It runs the VENDORED runtime only: no dependency on the EvalGlass skill or the
# coding agent after install (P13). PyYAML is the runtime's one third-party dependency.
# The exit code derives from the core verdict (0 pass/informational, 1 fail/blocked,
# 2 setup/infra) — never recomputed in CI.
name: evalglass
on: [pull_request]
jobs:
  evalglass:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install "pyyaml>=6.0"
      - name: Run EvalGlass (vendored runtime)
        run: >-
          PYTHONPATH=evals python -m _evalglass.harness.cli
          run --config evals/evalglass.yaml --format ci
"""

_GITKEEP_DIRS = ("rubrics", "calibration", "baselines", "reports")

# The single source of truth for what `scaffold` writes — `plan` reuses it so the
# reviewable install plan can never drift from what `install` actually creates.
_ASSETS: dict[str, str] = {
    "evals/evalglass.yaml": _CONFIG_YAML,
    "evals/datasets/sample.jsonl": _SAMPLE_DATASET,
    "evals/traces/sample.jsonl": _SAMPLE_TRACE,
    "evals/evaluators/answer_nonempty.py": _EVALUATOR_TEMPLATE,
    "evals/authority.json": json.dumps(AuthorityRecord().to_dict(), indent=2, sort_keys=True)
    + "\n",
    "evals/README.md": _README,
    "evals/ci/github-actions.yml": _CI_SNIPPET,
    **{f"evals/{d}/.gitkeep": "" for d in _GITKEEP_DIRS},
}

#: The host-owned files a fresh ``scaffold`` creates (the install plan reuses this).
SCAFFOLD_PATHS: tuple[str, ...] = tuple(_ASSETS)


@dataclass(frozen=True)
class ScaffoldResult:
    """What a scaffold run created vs. preserved (existing host files left untouched)."""

    created: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)


def scaffold(host_root: Path) -> ScaffoldResult:
    """Write host-owned starter assets under ``host_root/evals/``; never overwrite host files."""
    host_root = Path(host_root)
    if not host_root.is_dir():
        # Mirror vendoring: never invent a host tree for a mistyped root.
        raise InstallerError(
            f"scaffold: host root {host_root} does not exist or is not a directory"
        )

    created: list[str] = []
    preserved: list[str] = []
    for rel, content in _ASSETS.items():
        dest = host_root / rel
        if dest.exists():
            preserved.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        created.append(rel)

    return ScaffoldResult(created=created, preserved=preserved)
