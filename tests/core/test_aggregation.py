"""Aggregation over a metric's scores (EG-M0-4a).

Aggregation includes only ``scored`` + ``valid`` measurements and preserves the
counts of everything it excluded, so a summary can never hide that half its
inputs were blocked (``CLAUDE.md §9``). An aggregate over no eligible scores has
value ``None`` — not ``0.0``.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.aggregation import AggregatedMetric, aggregate
from evalglass.core.contracts import ContractError
from evalglass.core.registry import Aggregation
from evalglass.core.scores import Score, ScoreStatus, Validity


def _scored(value: float, validity: Validity = Validity.VALID) -> Score:
    return Score(
        metric="m",
        value=value,
        status=ScoreStatus.SCORED,
        validity=validity,
        evaluator_version="m@1",
    )


def _nonscored(status: ScoreStatus) -> Score:
    return Score(
        metric="m",
        value=None,
        status=status,
        validity=Validity.NOT_MEASURED,
        evaluator_version="m@1",
    )


def test_includes_only_scored_valid_and_counts_the_rest() -> None:
    scores = [
        _scored(1.0),
        _scored(0.0),
        _scored(0.5, validity=Validity.INVALID),  # measured but invalid -> excluded
        _nonscored(ScoreStatus.BLOCKED),
        _nonscored(ScoreStatus.SKIPPED),
    ]
    agg = aggregate("m", scores, Aggregation.MEAN)
    assert agg.included_count == 2
    assert agg.value == pytest.approx(0.5)  # mean of [1.0, 0.0]
    assert agg.status_counts["scored"] == 3
    assert agg.status_counts["blocked"] == 1
    assert agg.status_counts["skipped"] == 1


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (Aggregation.MEAN, 0.5),
        (Aggregation.MEDIAN, 0.5),
        (Aggregation.MIN, 0.0),
        (Aggregation.MAX, 1.0),
        (Aggregation.RATE, 0.5),  # success rate = mean of normalized scores
    ],
)
def test_aggregation_kinds(kind: Aggregation, expected: float) -> None:
    agg = aggregate("m", [_scored(0.0), _scored(1.0)], kind)
    assert agg.value == pytest.approx(expected)


def test_median_of_three() -> None:
    agg = aggregate("m", [_scored(0.0), _scored(0.2), _scored(1.0)], Aggregation.MEDIAN)
    assert agg.value == pytest.approx(0.2)


def test_no_eligible_scores_has_none_value_not_zero() -> None:
    agg = aggregate("m", [_nonscored(ScoreStatus.BLOCKED)], Aggregation.MEAN)
    assert agg.value is None
    assert agg.included_count == 0
    assert agg.status_counts["blocked"] == 1


def test_aggregation_none_kind_produces_no_value() -> None:
    agg = aggregate("m", [_scored(1.0)], Aggregation.NONE)
    assert agg.value is None
    assert agg.included_count == 1  # still counts what was eligible


def test_rate_of_all_failures_is_zero_not_one() -> None:
    """All-0.0 binary must report a 0% success rate, not 100%."""
    agg = aggregate("m", [_scored(0.0), _scored(0.0)], Aggregation.RATE)
    assert agg.value == pytest.approx(0.0)


def test_only_the_requested_metric_is_aggregated() -> None:
    """A mixed run-wide list must not let another metric leak into this summary."""
    other = Score(
        metric="other",
        value=1.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="other@1",
    )
    agg = aggregate("m", [_scored(0.0), other, _nonscored(ScoreStatus.BLOCKED)], Aggregation.MEAN)
    assert agg.value == pytest.approx(0.0)  # only m's single 0.0
    assert agg.included_count == 1
    assert agg.status_counts.get("scored") == 1


def test_aggregated_metric_round_trips() -> None:
    agg = aggregate("m", [_scored(1.0), _nonscored(ScoreStatus.ERROR)], Aggregation.MEAN)
    assert AggregatedMetric.from_dict(json.loads(json.dumps(agg.to_dict()))) == agg


@pytest.mark.parametrize("bad", [True, "3", 1.5, -1])
def test_from_dict_rejects_malformed_status_counts(bad: object) -> None:
    data = aggregate("m", [_scored(1.0)], Aggregation.MEAN).to_dict()
    data["status_counts"] = {"scored": bad}
    with pytest.raises(ContractError):
        AggregatedMetric.from_dict(data)
