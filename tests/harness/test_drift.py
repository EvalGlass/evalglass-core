"""EG-P4-1 — harness drift evaluation: honest labels over paired_comparison (first consumer)."""

from __future__ import annotations

from pathlib import Path

from evalglass.core.aggregation import aggregate
from evalglass.core.provenance import REQUIRED_DIMENSIONS, BaselineState, RunFingerprint
from evalglass.core.registry import Aggregation, Direction
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.core.verdict import decide_verdict
from evalglass.harness.drift import Comparability, DriftResult, evaluate_drift

_DIRECTIONS = {"faithfulness": Direction.HIGHER_IS_BETTER}


def _score(value: float, example_id: str, metric: str = "faithfulness") -> Score:
    return Score(metric, value, ScoreStatus.SCORED, Validity.VALID, "1", example_id=example_id)


def _record(
    scores: list[Score], baseline_state: BaselineState | None, run_id: str = "r"
) -> RunRecord:
    aggs = [aggregate(m, scores, Aggregation.MEAN) for m in sorted({s.metric for s in scores})]
    sc = Scorecard(
        verdict=decide_verdict([]), metrics=aggs, authority={}, baseline_state=baseline_state
    )
    dims = {d: {"x": 1} for d in REQUIRED_DIMENSIONS}
    return RunRecord(run_id=run_id, scorecard=sc, scores=scores, provenance=RunFingerprint.of(dims))


def test_comparable_regression_is_flagged() -> None:
    current = _record(
        [_score(0.5, "e1"), _score(0.5, "e2"), _score(0.5, "e3")], BaselineState.COMPARABLE
    )
    baseline = _record([_score(1.0, "e1"), _score(1.0, "e2"), _score(1.0, "e3")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    assert result.comparability is Comparability.COMPARABLE
    assert result.regressions() == ["faithfulness"]  # a consistent drop clears the interval


def test_within_noise_is_not_a_regression() -> None:
    current = _record([_score(1.0, "e1"), _score(0.0, "e2")], BaselineState.COMPARABLE)
    baseline = _record([_score(0.0, "e1"), _score(1.0, "e2")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    assert result.comparability is Comparability.COMPARABLE
    assert result.regressions() == []  # the paired interval spans zero → within_noise


def test_not_comparable_emits_no_regression() -> None:
    current = _record([_score(0.5, "e1"), _score(0.5, "e2")], BaselineState.NOT_COMPARABLE)
    baseline = _record([_score(1.0, "e1"), _score(1.0, "e2")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    assert result.comparability is Comparability.NOT_COMPARABLE
    assert result.regressions() == []  # never "no regression" — the honest state is not_comparable
    assert result.comparison is None


def test_missing_baseline_is_reported_honestly() -> None:
    current = _record([_score(0.5, "e1")], BaselineState.MISSING_BASELINE)
    result = evaluate_drift(current, None, _DIRECTIONS)
    assert result.comparability is Comparability.MISSING_BASELINE
    assert result.regressions() == []


def test_metric_without_direction_is_skipped_not_crashed() -> None:
    current = _record([_score(0.5, "e1"), _score(0.5, "e2")], BaselineState.COMPARABLE)
    baseline = _record([_score(1.0, "e1"), _score(1.0, "e2")], None, "base")
    result = evaluate_drift(current, baseline, {})  # no directions supplied
    assert result.comparability is Comparability.COMPARABLE
    assert "faithfulness" in result.skipped_metrics
    assert result.regressions() == []  # nothing to compare, never a crash


def test_round_trip() -> None:
    current = _record([_score(0.5, "e1"), _score(0.5, "e2")], BaselineState.COMPARABLE)
    baseline = _record([_score(1.0, "e1"), _score(1.0, "e2")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    assert DriftResult.from_dict(result.to_dict()) == result


def test_drift_result_carries_no_verdict_or_authority() -> None:
    current = _record([_score(0.5, "e1")], BaselineState.COMPARABLE)
    baseline = _record([_score(1.0, "e1")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    assert not hasattr(result, "verdict")
    assert not hasattr(result, "authority")
    assert not hasattr(result, "ci_should_fail")


# --- EG-P4-2: persistence + explanatory diagnostic (no verdict path; baseline untouched) ---------


def test_persist_drift_writes_json(tmp_path: Path) -> None:
    import json

    from evalglass.harness.drift import persist_drift

    current = _record([_score(0.5, "e1"), _score(0.5, "e2")], BaselineState.COMPARABLE)
    baseline = _record([_score(1.0, "e1"), _score(1.0, "e2")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    run_dir = tmp_path
    path = persist_drift(result, run_dir)
    assert path == run_dir / "drift.json"
    on_disk = DriftResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert on_disk == result


def test_with_drift_diagnostic_leaves_verdict_unchanged() -> None:
    from evalglass.harness.drift import with_drift_diagnostic

    current = _record(
        [_score(0.5, "e1"), _score(0.5, "e2"), _score(0.5, "e3")], BaselineState.COMPARABLE
    )
    baseline = _record([_score(1.0, "e1"), _score(1.0, "e2"), _score(1.0, "e3")], None, "base")
    result = evaluate_drift(current, baseline, _DIRECTIONS)
    updated = with_drift_diagnostic(current.scorecard, result)
    # The drift diagnostic is appended; the verdict, ci flag, metrics, and authority are unchanged.
    assert updated.verdict == current.scorecard.verdict
    assert updated.verdict.ci_should_fail == current.scorecard.verdict.ci_should_fail
    assert updated.metrics == current.scorecard.metrics
    assert any(d.code == "drift.regression" for d in updated.diagnostics)
    assert len(updated.diagnostics) == len(current.scorecard.diagnostics) + 1
