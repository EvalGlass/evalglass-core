"""EGTS-M2-2/-3: baseline comparability + data-policy egress-refusal proof.

Through the real harness (``run_config`` + the product ``baseline.promote``) in isolated
workspaces:

- **EGTS-M2-2 (baseline):** a comparable promoted baseline lets a required-baseline gate pass; a
  changed gating dimension (dataset, evaluator) is non-comparable and blocks; a missing baseline
  blocks. Negative control: a score delta without a comparable fingerprint fails the regression
  checker.
- **EGTS-M2-3 (data policy):** a forbidden source produces no host egress (the specimen marker is
  absent) and the gate blocks; a permitted source egresses and scores. Negative control: the
  no-egress checker fails on a permitted run (it really detects egress).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evalglass.core import RunRecord, Verdict
from evalglass.harness.baseline import promote
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config
from tests.egts.checkers import (
    CheckerError,
    check_baseline_state,
    check_no_egress,
    check_regression_comparable,
    check_verdict,
)
from tests.egts.workspace import make_workspace

_GATE = {"metric_status": "gating", "threshold_approval": "approved", "threshold": 0.5}


def _run(
    tmp_path: Path,
    *,
    requires_baseline: bool = False,
    baseline_path: str | None = None,
    dataset_name: str = "d.jsonl",
    evaluator_ref: str = "exact_match@1",
) -> RunRecord:
    (tmp_path / dataset_name).write_text(
        json.dumps({"input": "4", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    metric: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": evaluator_ref,
        "lens": "reference",
        "score_type": "binary",
        "dataset": dataset_name,
        "requires_baseline": requires_baseline,
        **_GATE,
    }
    raw: dict[str, object] = {
        "datasets": [
            {
                "path": dataset_name,
                "name": dataset_name,
                "status": "validated",
                "data_policy": "permitted",
            }
        ],
        "metrics": [metric],
    }
    if requires_baseline or baseline_path:
        baseline: dict[str, object] = {"comparison_requested": True}
        if baseline_path:
            baseline["path"] = baseline_path
        raw["baseline"] = baseline
    return run_config(RuntimeConfig.from_mapping(raw), tmp_path)


# --- EGTS-M2-2: baseline comparability ---------------------------------------


def test_comparable_baseline_allows_gate(tmp_path: Path) -> None:
    base = _run(tmp_path)
    promote(base, tmp_path / "baselines" / "b.json")
    record = _run(tmp_path, requires_baseline=True, baseline_path="baselines/b.json")
    check_baseline_state(record.scorecard, expected="comparable")
    check_regression_comparable(record.scorecard)  # comparable → regression claim is honest
    check_verdict(record.scorecard, expected=Verdict.PASS)
    # Negative control for the baseline-state checker: a wrong declared state must fail.
    with pytest.raises(CheckerError):
        check_baseline_state(record.scorecard, expected="missing_baseline")


def test_changed_dataset_is_not_comparable_and_blocks(tmp_path: Path) -> None:
    base = _run(tmp_path)
    promote(base, tmp_path / "baselines" / "b.json")
    record = _run(
        tmp_path, requires_baseline=True, baseline_path="baselines/b.json", dataset_name="d2.jsonl"
    )
    check_baseline_state(record.scorecard, expected="not_comparable")
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)
    # Negative control: a non-comparable run cannot back a regression claim.
    with pytest.raises(CheckerError):
        check_regression_comparable(record.scorecard)


def test_changed_evaluator_is_not_comparable(tmp_path: Path) -> None:
    base = _run(tmp_path)
    promote(base, tmp_path / "baselines" / "b.json")
    record = _run(
        tmp_path,
        requires_baseline=True,
        baseline_path="baselines/b.json",
        evaluator_ref="set_overlap@1",
    )
    check_baseline_state(record.scorecard, expected="not_comparable")


def test_missing_baseline_blocks(tmp_path: Path) -> None:
    record = _run(tmp_path, requires_baseline=True)  # comparison requested, no baseline file
    check_baseline_state(record.scorecard, expected="missing_baseline")
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)


# --- EGTS-M2-3: data-policy egress refusal -----------------------------------

_MARK_ECHO = (
    "import pathlib; pathlib.Path('CALLED').write_text('1')\n"
    "import sys, json\nprint(json.dumps({'output': json.load(sys.stdin)['input']}))\n"
)


def _policy_run(tmp_path: Path, fixture_id: str, *, policy: str) -> tuple[RunRecord, Path]:
    config = (
        f"datasets:\n  - path: datasets/d.jsonl\n    status: validated\n    data_policy: {policy}\n"
        f"task:\n  argv: [{json.dumps(sys.executable)}, specimen.py]\n  timeout_s: 10\n"
        "metrics:\n  - name: exact_match\n    evaluator_ref: exact_match@1\n    lens: reference\n"
        "    score_type: binary\n    dataset: datasets/d.jsonl\n"
        "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5\n"
    )
    ws = make_workspace(
        tmp_path,
        fixture_id,
        config=config,
        datasets={"d.jsonl": json.dumps({"input": "4", "reference": "4"}) + "\n"},  # output-less
    )
    (ws.root / "specimen.py").write_text(_MARK_ECHO, encoding="utf-8")
    record = run_config(load_config(str(ws.config_path)), ws.root)
    return record, ws.root


def test_forbidden_policy_no_egress_and_blocks(tmp_path: Path) -> None:
    record, root = _policy_run(tmp_path, "m2-forbidden", policy="forbidden")
    check_no_egress(root)  # the specimen never ran — no marker
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)


def test_permitted_policy_egresses_and_scores(tmp_path: Path) -> None:
    record, root = _policy_run(tmp_path, "m2-permitted", policy="permitted")
    check_verdict(record.scorecard, expected=Verdict.PASS)
    # Negative control: a permitted run DID egress, so the no-egress checker must fail.
    with pytest.raises(CheckerError):
        check_no_egress(root)
