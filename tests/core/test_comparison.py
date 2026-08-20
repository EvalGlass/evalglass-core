"""Tests for paired baseline comparison (M7 T5, G6).

A dropped number is not a regression until the paired interval clears zero.
See src/evalglass/core/comparison.py and docs/TETA_REDESIGN.md §6.2.
"""

from __future__ import annotations

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.comparison import DeltaOutcome, metric_delta, paired_comparison
from evalglass.core.registry import Direction
from evalglass.core.scores import Score, ScoreStatus, Validity


def _s(metric: str, eid: str, value: float | None, *, ok: bool = True) -> Score:
    if ok:
        return Score(metric, value, ScoreStatus.SCORED, Validity.VALID, "1", example_id=eid)
    return Score(metric, None, ScoreStatus.BLOCKED, Validity.NOT_MEASURED, "1", example_id=eid)


def test_clear_regression() -> None:
    cur = [_s("m", f"e{i}", 0.5) for i in range(4)]
    base = [_s("m", f"e{i}", 0.9) for i in range(4)]
    d = metric_delta("m", cur, base, Direction.HIGHER_IS_BETTER)
    assert d.n_paired == 4
    assert d.delta == pytest.approx(-0.4)
    assert d.outcome is DeltaOutcome.REGRESSION  # dropped, higher-is-better


def test_clear_improvement() -> None:
    cur = [_s("m", f"e{i}", 0.9) for i in range(4)]
    base = [_s("m", f"e{i}", 0.5) for i in range(4)]
    d = metric_delta("m", cur, base, Direction.HIGHER_IS_BETTER)
    assert d.outcome is DeltaOutcome.IMPROVEMENT


def test_lower_is_better_flips_sign() -> None:
    # value went UP; for lower-is-better that is a regression.
    cur = [_s("m", f"e{i}", 0.9) for i in range(4)]
    base = [_s("m", f"e{i}", 0.5) for i in range(4)]
    d = metric_delta("m", cur, base, Direction.LOWER_IS_BETTER)
    assert d.outcome is DeltaOutcome.REGRESSION


def test_within_noise_when_interval_spans_zero() -> None:
    # tiny, mixed-sign differences -> interval contains 0.
    cur = [_s("m", "e0", 0.80), _s("m", "e1", 0.82), _s("m", "e2", 0.79)]
    base = [_s("m", "e0", 0.81), _s("m", "e1", 0.80), _s("m", "e2", 0.81)]
    d = metric_delta("m", cur, base, Direction.HIGHER_IS_BETTER)
    assert d.outcome is DeltaOutcome.WITHIN_NOISE


def test_single_shared_item_is_unresolved() -> None:
    d = metric_delta("m", [_s("m", "e0", 0.9)], [_s("m", "e0", 0.5)], Direction.HIGHER_IS_BETTER)
    assert d.n_paired == 1
    assert d.interval is None
    assert d.outcome is DeltaOutcome.UNRESOLVED


def test_no_overlap_is_unresolved() -> None:
    d = metric_delta("m", [_s("m", "a", 0.9)], [_s("m", "b", 0.5)], Direction.HIGHER_IS_BETTER)
    assert d.n_paired == 0
    assert d.outcome is DeltaOutcome.UNRESOLVED


def test_only_aggregatable_items_pair() -> None:
    cur = [_s("m", "e0", 0.5), _s("m", "e1", None, ok=False)]
    base = [_s("m", "e0", 0.9), _s("m", "e1", 0.9)]
    d = metric_delta("m", cur, base, Direction.HIGHER_IS_BETTER)
    assert d.n_paired == 1  # e1 excluded (blocked in current)


def test_paired_comparison_requires_direction() -> None:
    cur = [_s("m", "e0", 0.5)]
    base = [_s("m", "e0", 0.9)]
    with pytest.raises(ContractError):
        paired_comparison(cur, base, {}, baseline_run_id="b1")


def test_paired_comparison_round_trip_dict() -> None:
    cur = [_s("m", f"e{i}", 0.5) for i in range(3)]
    base = [_s("m", f"e{i}", 0.9) for i in range(3)]
    cmp = paired_comparison(cur, base, {"m": Direction.HIGHER_IS_BETTER}, baseline_run_id="b1")
    d = cmp.to_dict()
    assert d["baseline_run_id"] == "b1"
    assert d["deltas"]["m"]["outcome"] == "regression"
    assert "interval" in d["deltas"]["m"]
