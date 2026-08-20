"""Baseline loading + comparability wiring (EG-M2-2a).

A baseline is a promoted RunRecord; the runner loads its provenance fingerprint and the core
decides comparability. The trust-critical cases: a *comparable* baseline lets a required-baseline
gate evaluate; a *changed gating dimension* makes it non-comparable and the gate **blocks** (never
a fabricated regression); a *missing* baseline with the comparison requested also blocks. A
configured-but-unloadable baseline is a setup error, never a silent "no baseline".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import BaselineState, RunRecord, Verdict
from evalglass.harness.baseline import load_baseline, promote
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.runner import run_config

_REC = {"input": "4", "output": "4", "reference": "4"}


def _run(
    tmp_path: Path,
    *,
    requires_baseline: bool,
    baseline_path: str | None = None,
    comparison: bool = False,
    dataset_name: str = "d.jsonl",
) -> RunRecord:
    (tmp_path / dataset_name).write_text(json.dumps(_REC) + "\n", encoding="utf-8")
    metric: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": dataset_name,
        "metric_status": "gating",
        "threshold_approval": "approved",
        "threshold": 0.5,
        "requires_baseline": requires_baseline,
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
    if baseline_path is not None or comparison:
        baseline: dict[str, object] = {"comparison_requested": comparison}
        if baseline_path is not None:
            baseline["path"] = baseline_path
        raw["baseline"] = baseline
    return run_config(RuntimeConfig.from_mapping(raw), tmp_path)


# --- loader (fail-closed) ----------------------------------------------------


def test_load_baseline_returns_provenance(tmp_path: Path) -> None:
    base = _run(tmp_path, requires_baseline=False)
    path = tmp_path / "b.json"
    promote(base, path)
    assert load_baseline(path).dimensions == base.provenance.dimensions


def test_missing_baseline_file_is_setup_error(tmp_path: Path) -> None:
    with pytest.raises(SetupError) as exc:
        load_baseline(tmp_path / "nope.json")
    assert exc.value.diagnostic.code == "baseline_not_found"


def test_malformed_baseline_file_is_setup_error(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_baseline(path)
    assert exc.value.diagnostic.code == "baseline_invalid"


def test_undecodable_baseline_file_is_setup_error(tmp_path: Path) -> None:
    # Invalid UTF-8 must be a setup diagnostic, not a UnicodeDecodeError traceback.
    path = tmp_path / "b.json"
    path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(SetupError) as exc:
        load_baseline(path)
    assert exc.value.diagnostic.code == "baseline_unreadable"


# --- comparability wiring (authority blast radius) ---------------------------


def test_comparable_baseline_allows_regression_gate(tmp_path: Path) -> None:
    base = _run(tmp_path, requires_baseline=False)
    promote(base, tmp_path / "baselines" / "b.json")
    record = _run(
        tmp_path, requires_baseline=True, baseline_path="baselines/b.json", comparison=True
    )
    assert record.scorecard.baseline_state is BaselineState.COMPARABLE
    assert record.scorecard.verdict.verdict == Verdict.PASS


def test_changed_gating_dimension_is_not_comparable_and_blocks(tmp_path: Path) -> None:
    base = _run(tmp_path, requires_baseline=False, dataset_name="d.jsonl")
    promote(base, tmp_path / "baselines" / "b.json")
    # A different dataset changes the 'dataset' gating dimension → non-comparable.
    record = _run(
        tmp_path,
        requires_baseline=True,
        baseline_path="baselines/b.json",
        comparison=True,
        dataset_name="d2.jsonl",
    )
    assert record.scorecard.baseline_state is BaselineState.NOT_COMPARABLE
    assert record.scorecard.verdict.verdict == Verdict.BLOCKED


def test_missing_baseline_with_required_gate_blocks(tmp_path: Path) -> None:
    record = _run(
        tmp_path, requires_baseline=True, comparison=True
    )  # comparison asked, no baseline
    assert record.scorecard.baseline_state is BaselineState.MISSING_BASELINE
    assert record.scorecard.verdict.verdict == Verdict.BLOCKED
