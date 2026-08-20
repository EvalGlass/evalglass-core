"""Typed paired comparison as primary truth (Epic D / D4).

A run persists a typed ComparisonResult on its Scorecard: a numeric per-metric delta exists only
when the run is comparable; a non-comparable run records the changed fingerprint dimensions and no
delta; the object round-trips, is state-consistent under anti-tamper, and sets no verdict/exit.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from evalglass.core import ContractError, RunRecord
from evalglass.core.comparison import DeltaOutcome
from evalglass.core.provenance import BaselineState
from evalglass.harness.baseline import promote
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config


def _cfg(tmp_path: Path, *, output: str, baseline: bool, version: str = "1") -> RuntimeConfig:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "4", "output": output, "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg: dict[str, object] = {
        "run": {"id": "current"},
        "datasets": [
            {
                "path": "d.jsonl",
                "status": "validated",
                "data_policy": "permitted",
                "version": version,
            }
        ],
        "metrics": [
            {
                "name": "correctness",
                "evaluator_ref": "exact_match@1",
                "lens": "reference",
                "score_type": "binary",
                "dataset": "d.jsonl",
                "threshold": 1.0,
            }
        ],
    }
    if baseline:
        cfg["baseline"] = {"path": "baselines/b.json", "comparison_requested": True}
    return RuntimeConfig.from_mapping(cfg)


def _make_baseline(tmp_path: Path, output: str) -> None:
    base = run_config(_cfg(tmp_path, output=output, baseline=False), tmp_path)
    promote(replace(base, run_id="baseline-1"), tmp_path / "baselines" / "b.json")


def test_comparable_run_persists_a_paired_delta(tmp_path: Path) -> None:
    _make_baseline(tmp_path, output="4")  # baseline scored 1.0
    record = run_config(_cfg(tmp_path, output="4", baseline=True), tmp_path)
    comparison = record.scorecard.comparison
    assert comparison is not None
    assert comparison.state is BaselineState.COMPARABLE
    assert comparison.baseline_run_id == "baseline-1"
    assert comparison.comparison is not None
    delta = comparison.comparison.deltas["correctness"]
    assert delta.n_paired == 1
    assert delta.delta == 0.0  # 1.0 - 1.0
    # A single pair cannot resolve an interval -> unresolved, no improvement/regression claim.
    assert delta.outcome is DeltaOutcome.UNRESOLVED


def test_direction_adjusted_delta_present_for_comparable(tmp_path: Path) -> None:
    _make_baseline(tmp_path, output="4")
    record = run_config(_cfg(tmp_path, output="4", baseline=True), tmp_path)
    comparison = record.scorecard.comparison
    assert comparison is not None
    assert comparison.comparison is not None
    delta = comparison.comparison.deltas["correctness"]
    # higher_is_better -> direction-adjusted equals the raw delta.
    assert delta.direction_adjusted_delta == delta.delta


def test_non_comparable_run_has_no_delta_and_lists_changed_dimensions(tmp_path: Path) -> None:
    _make_baseline(tmp_path, output="4")  # baseline captured at dataset version "1"
    # Bump the dataset version -> a gating fingerprint dimension changes -> not comparable.
    record = run_config(_cfg(tmp_path, output="4", baseline=True, version="2"), tmp_path)
    comparison = record.scorecard.comparison
    assert comparison is not None
    assert comparison.state is BaselineState.NOT_COMPARABLE
    assert comparison.comparison is None  # no numeric delta for a non-comparable run
    assert comparison.changed_dimensions  # explains why


def test_no_baseline_configured_yields_no_comparison(tmp_path: Path) -> None:
    record = run_config(_cfg(tmp_path, output="4", baseline=False), tmp_path)
    assert record.scorecard.comparison is None  # byte-compatible: no comparison object at all


def test_comparison_round_trips(tmp_path: Path) -> None:
    _make_baseline(tmp_path, output="4")
    record = run_config(_cfg(tmp_path, output="4", baseline=True), tmp_path)
    restored = RunRecord.from_dict(record.to_dict())
    assert restored.scorecard.comparison == record.scorecard.comparison


def test_tampered_comparison_state_fails_closed(tmp_path: Path) -> None:
    _make_baseline(tmp_path, output="4")
    record = run_config(_cfg(tmp_path, output="4", baseline=True), tmp_path)
    payload = record.to_dict()
    # Claim "comparable" while the scorecard's own baseline_state says otherwise is caught; here we
    # flip the comparison to a state that contradicts baseline_state.
    payload["scorecard"]["comparison"]["state"] = "not_comparable"
    payload["scorecard"]["comparison"].pop("comparison", None)
    with pytest.raises(ContractError, match="comparison state"):
        RunRecord.from_dict(payload)


def test_comparison_sets_no_verdict_or_exit(tmp_path: Path) -> None:
    # A comparable run with a metric that dropped stays informational (no gate) — comparison never
    # sets ci_should_fail; the exit path is the Verdict Engine's alone.
    _make_baseline(tmp_path, output="4")  # baseline 1.0
    record = run_config(_cfg(tmp_path, output="wrong", baseline=True), tmp_path)  # current 0.0
    assert record.scorecard.verdict.verdict.value == "informational"
    assert record.scorecard.verdict.ci_should_fail is False
