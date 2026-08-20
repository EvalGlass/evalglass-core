"""Tests for the Estimate type and its interval selection (M7 T1, G1).

See src/evalglass/core/estimate.py and docs/TETA_REDESIGN.md §5.
"""

from __future__ import annotations

import math

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.aggregation import aggregate
from evalglass.core.contracts import UnitKind
from evalglass.core.estimate import Estimate, Interval, IntervalMethod, estimate
from evalglass.core.registry import Aggregation, Direction, Lens, MetricSpec, ScoreType
from evalglass.core.scores import Score, ScoreStatus, Validity


def _spec(name: str, score_type: ScoreType, aggregation: Aggregation) -> MetricSpec:
    return MetricSpec(
        name=name,
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=score_type,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="test",
        score_range=(0.0, 1.0) if score_type is ScoreType.CONTINUOUS else None,
        aggregation=aggregation,
    )


def _scored(metric: str, value: float) -> Score:
    return Score(
        metric=metric,
        value=value,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="1",
    )


def _blocked(metric: str) -> Score:
    return Score(
        metric=metric,
        value=None,
        status=ScoreStatus.BLOCKED,
        validity=Validity.NOT_MEASURED,
        evaluator_version="1",
    )


def _diag_codes(est: Estimate) -> set[str]:
    return {d.code for d in est.diagnostics}


# --- proportion (binary) ---------------------------------------------------


def test_binary_all_pass_uses_wilson_and_rule_of_three() -> None:
    spec = _spec("m", ScoreType.BINARY, Aggregation.RATE)
    est = estimate(spec, [_scored("m", 1.0)] * 3)
    assert est.point == 1.0
    assert est.n_effective == 3
    assert est.interval is not None
    assert est.interval.method is IntervalMethod.WILSON
    assert est.interval.upper == 1.0
    assert est.interval.lower > 0.0  # non-degenerate
    assert "rule_of_three" in _diag_codes(est)


def test_binary_mixed_no_rule_of_three() -> None:
    spec = _spec("m", ScoreType.BINARY, Aggregation.MEAN)
    est = estimate(spec, [_scored("m", 1.0), _scored("m", 1.0), _scored("m", 0.0)])
    assert est.point is not None
    assert math.isclose(est.point, 2 / 3)
    assert est.interval is not None
    assert est.interval.method is IntervalMethod.WILSON
    assert "rule_of_three" not in _diag_codes(est)


def test_binary_all_fail_reports_success_upper_bound() -> None:
    spec = _spec("m", ScoreType.BINARY, Aggregation.RATE)
    est = estimate(spec, [_scored("m", 0.0)] * 3)
    assert est.point == 0.0
    assert est.interval is not None
    assert est.interval.lower == 0.0
    d = next(d for d in est.diagnostics if d.code == "rule_of_three")
    assert d.details["success_rate_95pct_upper_bound"] == 1.0  # 3/3 capped


# --- continuous mean -------------------------------------------------------


def test_continuous_mean_uses_student_t() -> None:
    spec = _spec("m", ScoreType.CONTINUOUS, Aggregation.MEAN)
    est = estimate(spec, [_scored("m", 0.9), _scored("m", 0.95), _scored("m", 1.0)])
    assert est.point is not None
    assert math.isclose(est.point, 0.95)
    assert est.interval is not None
    assert est.interval.method is IntervalMethod.STUDENT_T
    assert "low_reliability_small_n" in _diag_codes(est)
    # t-interval at n=3 is wider than the range would suggest.
    assert est.interval.lower < 0.9


def test_continuous_mean_interval_clamps_to_score_range() -> None:
    # A [0,1] metric near the ceiling: the raw Student-t upper would exceed 1.0; clamp to range.
    spec = _spec("m", ScoreType.CONTINUOUS, Aggregation.MEAN)
    est = estimate(spec, [_scored("m", 0.95), _scored("m", 1.0), _scored("m", 0.98)])
    assert est.interval is not None
    assert est.interval.upper <= 1.0
    assert est.interval.lower >= 0.0


def test_continuous_mean_n1_no_interval() -> None:
    spec = _spec("m", ScoreType.CONTINUOUS, Aggregation.MEAN)
    est = estimate(spec, [_scored("m", 0.7)])
    assert est.point == 0.7
    assert est.n_effective == 1
    assert est.interval is None
    assert "low_reliability_small_n" in _diag_codes(est)


# --- order statistics / none ----------------------------------------------


def test_min_aggregation_has_no_interval() -> None:
    spec = _spec("m", ScoreType.CONTINUOUS, Aggregation.MIN)
    est = estimate(spec, [_scored("m", 0.3), _scored("m", 0.9)])
    assert est.point == 0.3
    assert est.interval is None
    assert "no_interval_for_aggregation" in _diag_codes(est)


def test_none_aggregation_no_point_no_interval() -> None:
    spec = _spec("m", ScoreType.CONTINUOUS, Aggregation.NONE)
    est = estimate(spec, [_scored("m", 0.5)])
    assert est.point is None
    assert est.interval is None


# --- exclusion / consistency ----------------------------------------------


def test_excluded_scores_do_not_count() -> None:
    spec = _spec("m", ScoreType.BINARY, Aggregation.RATE)
    scores = [_scored("m", 1.0), _scored("m", 1.0), _blocked("m")]
    est = estimate(spec, scores)
    assert est.n_effective == 2  # blocked excluded
    assert est.point == 1.0


def test_point_matches_aggregate() -> None:
    spec = _spec("m", ScoreType.CONTINUOUS, Aggregation.MEAN)
    scores = [_scored("m", 0.2), _scored("m", 0.4), _scored("m", 0.9)]
    est = estimate(spec, scores)
    assert est.point == aggregate("m", scores, Aggregation.MEAN).value


def test_only_own_metric_counts() -> None:
    spec = _spec("m", ScoreType.BINARY, Aggregation.RATE)
    est = estimate(spec, [_scored("m", 1.0), _scored("other", 0.0)])
    assert est.n_effective == 1
    assert est.point == 1.0


# --- serialization + invariants -------------------------------------------


def test_estimate_round_trip() -> None:
    spec = _spec("m", ScoreType.BINARY, Aggregation.RATE)
    est = estimate(spec, [_scored("m", 1.0), _scored("m", 0.0)])
    again = Estimate.from_dict(est.to_dict())
    assert again.to_dict() == est.to_dict()


def test_interval_rejects_inverted_bounds() -> None:
    with pytest.raises(ContractError):
        Interval(IntervalMethod.WILSON, 0.95, 0.8, 0.2)


def test_interval_rejects_none_method() -> None:
    with pytest.raises(ContractError):
        Interval(IntervalMethod.NONE, 0.95, 0.2, 0.8)


def test_interval_rejects_bad_level() -> None:
    with pytest.raises(ContractError):
        Interval(IntervalMethod.WILSON, 1.5, 0.2, 0.8)


def test_estimate_rejects_interval_without_point() -> None:
    with pytest.raises(ContractError):
        Estimate(
            metric="m",
            point=None,
            n_effective=0,
            interval=Interval(IntervalMethod.WILSON, 0.95, 0.1, 0.9),
        )
