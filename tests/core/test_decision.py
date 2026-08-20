"""Tests for DecisionPolicy and the pure apply_policy decision (M7 T2, G2).

The headline case: a metric that is perfect on the point estimate but whose
confidence bound does not clear the threshold must FAIL under the safe default —
the exact "n=3 is not proof" gap alpha's point-vs-threshold verdict could not see.

See src/evalglass/core/decision.py and docs/TETA_REDESIGN.md §4.5.
"""

from __future__ import annotations

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.contracts import UnitKind
from evalglass.core.decision import (
    DecisionOutcome,
    DecisionPolicy,
    DecisionStatistic,
    apply_policy,
)
from evalglass.core.estimate import Estimate, Interval, IntervalMethod, estimate
from evalglass.core.registry import Aggregation, Direction, Lens, MetricSpec, ScoreType
from evalglass.core.scores import Score, ScoreStatus, Validity


def _spec(agg: Aggregation = Aggregation.RATE) -> MetricSpec:
    return MetricSpec(
        name="m",
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="t",
        aggregation=agg,
    )


def _scored(value: float) -> Score:
    return Score("m", value, ScoreStatus.SCORED, Validity.VALID, "1")


# --- statistic resolution --------------------------------------------------


def test_default_statistic_is_conservative_bound_for_direction() -> None:
    hib = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    assert hib.effective_statistic() is DecisionStatistic.LOWER_CONFIDENCE_BOUND
    lib = DecisionPolicy(threshold=0.2, direction=Direction.LOWER_IS_BETTER)
    assert lib.effective_statistic() is DecisionStatistic.UPPER_CONFIDENCE_BOUND


def test_explicit_statistic_overrides_default() -> None:
    p = DecisionPolicy(
        threshold=0.8,
        direction=Direction.HIGHER_IS_BETTER,
        decision_statistic=DecisionStatistic.POINT,
    )
    assert p.effective_statistic() is DecisionStatistic.POINT


# --- the headline rigor case ----------------------------------------------


def test_perfect_point_but_wide_interval_fails_under_lcb() -> None:
    # 3/3 -> point 1.0, Wilson lower ~0.44; threshold 0.8; LCB default -> FAIL.
    est = estimate(_spec(), [_scored(1.0)] * 3)
    assert est.point == 1.0
    policy = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    out = apply_policy(policy, est)
    assert out.passed is False
    assert out.statistic is DecisionStatistic.LOWER_CONFIDENCE_BOUND
    assert out.statistic_value is not None
    assert out.statistic_value < 0.8


def test_same_estimate_passes_under_named_point_smoke_policy() -> None:
    est = estimate(_spec(), [_scored(1.0)] * 3)
    policy = DecisionPolicy(
        threshold=0.8,
        direction=Direction.HIGHER_IS_BETTER,
        decision_statistic=DecisionStatistic.POINT,
    )
    out = apply_policy(policy, est)
    assert out.passed is True
    assert out.statistic_value == 1.0


def test_large_sample_lower_bound_clears_threshold() -> None:
    est = estimate(_spec(), [_scored(1.0)] * 400)
    policy = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    out = apply_policy(policy, est)
    assert out.passed is True  # Wilson lower for 400/400 comfortably above 0.8


# --- blocks (inadequate evidence, never a guess) --------------------------


def test_insufficient_samples_blocks() -> None:
    est = estimate(_spec(), [_scored(1.0)])
    policy = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    out = apply_policy(policy, est)
    assert out.blocked
    assert out.block_reason == "insufficient_samples"


def test_missing_value_blocks() -> None:
    est = Estimate(metric="m", point=None, n_effective=0)
    policy = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    assert apply_policy(policy, est).block_reason == "no_measured_value"


def test_excessive_missing_blocks() -> None:
    est = estimate(_spec(), [_scored(1.0)] * 10)
    policy = DecisionPolicy(
        threshold=0.5, direction=Direction.HIGHER_IS_BETTER, max_missing_fraction=0.1
    )
    out = apply_policy(policy, est, missing_fraction=0.5)
    assert out.block_reason == "excessive_missing_evidence"


def test_bound_required_but_unavailable_blocks() -> None:
    # A continuous mean at n below min still has enough n but no interval available.
    est = Estimate(metric="m", point=0.9, n_effective=3, interval=None)
    policy = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER, min_n_effective=2)
    out = apply_policy(policy, est)
    assert out.block_reason == "decision_statistic_unavailable"


def test_point_policy_needs_no_interval() -> None:
    est = Estimate(metric="m", point=0.9, n_effective=3, interval=None)
    policy = DecisionPolicy(
        threshold=0.8,
        direction=Direction.HIGHER_IS_BETTER,
        decision_statistic=DecisionStatistic.POINT,
    )
    assert apply_policy(policy, est).passed is True


# --- lower-is-better -------------------------------------------------------


def test_lower_is_better_uses_upper_bound() -> None:
    est = Estimate(
        metric="m",
        point=0.1,
        n_effective=50,
        interval=Interval(IntervalMethod.WILSON, 0.95, 0.05, 0.18),
    )
    policy = DecisionPolicy(threshold=0.15, direction=Direction.LOWER_IS_BETTER)
    out = apply_policy(policy, est)
    # upper bound 0.18 > threshold 0.15 -> fail (the point 0.1 alone would pass)
    assert out.passed is False
    assert out.statistic_value == 0.18


# --- digest + serialization ------------------------------------------------


def test_digest_is_stable_and_field_sensitive() -> None:
    base = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    assert (
        base.digest()
        == DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER).digest()
    )
    assert (
        base.digest()
        != DecisionPolicy(threshold=0.81, direction=Direction.HIGHER_IS_BETTER).digest()
    )
    assert (
        base.digest()
        != DecisionPolicy(
            threshold=0.8, direction=Direction.HIGHER_IS_BETTER, min_n_effective=5
        ).digest()
    )


def test_implicit_and_explicit_default_statistic_hash_equal() -> None:
    implicit = DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER)
    explicit = DecisionPolicy(
        threshold=0.8,
        direction=Direction.HIGHER_IS_BETTER,
        decision_statistic=DecisionStatistic.LOWER_CONFIDENCE_BOUND,
    )
    assert implicit.digest() == explicit.digest()


def test_round_trip() -> None:
    p = DecisionPolicy(
        threshold=0.8,
        direction=Direction.HIGHER_IS_BETTER,
        decision_statistic=DecisionStatistic.POINT,
        min_n_effective=10,
        max_missing_fraction=0.2,
        interval_level=0.9,
        required_study="agreement",
        policy_id="p1",
    )
    assert DecisionPolicy.from_dict(p.to_dict()) == p


# --- invariants ------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold": float("nan")},
        {"threshold": "x"},
        {"min_n_effective": 0},
        {"max_missing_fraction": 1.5},
        {"interval_level": 0.0},
        {"interval_level": 1.0},
    ],
)
def test_invalid_policies_rejected(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {"threshold": 0.8, "direction": Direction.HIGHER_IS_BETTER}
    base.update(kwargs)
    with pytest.raises(ContractError):
        DecisionPolicy(**base)  # type: ignore[arg-type]


def test_outcome_blocked_property() -> None:
    assert DecisionOutcome(None, DecisionStatistic.POINT, None, "x").blocked
    assert not DecisionOutcome(True, DecisionStatistic.POINT, 1.0).blocked
