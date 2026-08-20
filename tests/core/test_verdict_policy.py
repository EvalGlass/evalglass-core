"""Verdict Engine + DecisionPolicy: gate on the confidence bound (M7 T2c, G2).

A policy-bearing gate decides via apply_policy over the Estimate, so a point-perfect
but wide-interval gate blocks/fails instead of passing. A gate with no policy keeps
the legacy point-vs-threshold behavior (proved backward-compatible here too).

See src/evalglass/core/verdict.py and docs/TETA_REDESIGN.md §4.5.
"""

from __future__ import annotations

from evalglass.core.authority import AuthorityLevel, ResolvedAuthority
from evalglass.core.decision import DecisionPolicy, DecisionStatistic
from evalglass.core.estimate import Estimate, Interval, IntervalMethod
from evalglass.core.registry import Direction
from evalglass.core.verdict import GateInput, Verdict, decide_verdict


def _gating() -> ResolvedAuthority:
    return ResolvedAuthority(can_gate=True, level=AuthorityLevel.GATING, blocked=False)


def _est(point: float, n: int, lower: float, upper: float) -> Estimate:
    return Estimate(
        metric="m",
        point=point,
        n_effective=n,
        interval=Interval(IntervalMethod.WILSON, 0.95, lower, upper),
    )


def test_wide_interval_fails_under_lcb_policy() -> None:
    # point 1.0 but LCB 0.44 < threshold 0.8 -> FAIL (not a pass).
    gate = GateInput(
        metric="m",
        resolved=_gating(),
        value=1.0,
        estimate=_est(1.0, 3, 0.44, 1.0),
        decision_policy=DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER),
    )
    payload = decide_verdict([gate])
    assert payload.verdict is Verdict.FAIL
    assert payload.failing_gates == ["m"]
    assert payload.reasons["m"] == ["lower_confidence_bound_below_threshold"]


def test_insufficient_samples_blocks_under_policy() -> None:
    gate = GateInput(
        metric="m",
        resolved=_gating(),
        value=1.0,
        estimate=Estimate(metric="m", point=1.0, n_effective=1),
        decision_policy=DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER),
    )
    payload = decide_verdict([gate])
    assert payload.verdict is Verdict.BLOCKED
    assert payload.reasons["m"] == ["insufficient_samples"]


def test_lower_bound_clears_threshold_passes() -> None:
    gate = GateInput(
        metric="m",
        resolved=_gating(),
        value=0.99,
        estimate=_est(0.99, 400, 0.85, 1.0),
        decision_policy=DecisionPolicy(threshold=0.8, direction=Direction.HIGHER_IS_BETTER),
    )
    assert decide_verdict([gate]).verdict is Verdict.PASS


def test_point_smoke_policy_passes_small_n() -> None:
    gate = GateInput(
        metric="m",
        resolved=_gating(),
        value=1.0,
        estimate=_est(1.0, 3, 0.44, 1.0),
        decision_policy=DecisionPolicy(
            threshold=0.8,
            direction=Direction.HIGHER_IS_BETTER,
            decision_statistic=DecisionStatistic.POINT,
            min_n_effective=1,
        ),
    )
    assert decide_verdict([gate]).verdict is Verdict.PASS


def test_policy_missing_fraction_blocks() -> None:
    # 8 scored + 2 excluded -> missing 0.2 > max 0.1 -> blocked.
    gate = GateInput(
        metric="m",
        resolved=_gating(),
        value=1.0,
        excluded_count=2,
        estimate=_est(1.0, 8, 0.63, 1.0),
        decision_policy=DecisionPolicy(
            threshold=0.5,
            direction=Direction.HIGHER_IS_BETTER,
            decision_statistic=DecisionStatistic.POINT,
            max_missing_fraction=0.1,
        ),
    )
    payload = decide_verdict([gate])
    assert payload.verdict is Verdict.BLOCKED
    assert payload.reasons["m"] == ["excessive_missing_evidence"]


def test_no_policy_uses_legacy_point_path() -> None:
    # Backward compatibility: no policy -> point 1.0 >= threshold 0.8 -> PASS.
    gate = GateInput(metric="m", resolved=_gating(), value=1.0, threshold=0.8)
    assert decide_verdict([gate]).verdict is Verdict.PASS


def test_no_policy_legacy_excluded_blocks() -> None:
    gate = GateInput(metric="m", resolved=_gating(), value=1.0, threshold=0.8, excluded_count=1)
    payload = decide_verdict([gate])
    assert payload.verdict is Verdict.BLOCKED
    assert payload.reasons["m"] == ["incomplete_measurement"]
