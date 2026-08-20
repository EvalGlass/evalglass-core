"""Built-in: trajectory_shape@1 — domain-neutral aggregate over a richer unit (EG-M5-5 S1b)."""

from __future__ import annotations

import pytest

from evalglass.core import (
    EvalUnit,
    EvidenceBundle,
    Example,
    Score,
    ScoreStatus,
    UnitKind,
    Validity,
)
from evalglass.core.builtins import BUILTINS, trajectory_shape
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType


def _spec() -> MetricSpec:
    return MetricSpec(
        name="trajectory.shape",
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.TRAJECTORY,
        score_type=ScoreType.CONTINUOUS,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref=trajectory_shape.VERSION,
        score_range=(0.0, 1.0),
    )


def _example(*, kind: UnitKind, members: list[str], output: object) -> Example:
    unit = EvalUnit(unit_id="agg-1", kind=kind, trace_id="t1", members=members)
    return Example(example_id="agg-1", input=None, output=output, unit=unit)


def _score(example: Example) -> Score:
    ctx = EvaluatorContext(spec=_spec(), params={})
    return trajectory_shape.evaluate(example, ctx, EvidenceBundle())


def test_registered_in_builtins() -> None:
    assert BUILTINS[trajectory_shape.VERSION] is trajectory_shape.evaluate


def test_complete_trajectory_scores_one() -> None:
    score = _score(_example(kind=UnitKind.TRAJECTORY, members=["a", "b"], output=["x", "y"]))
    assert score.status is ScoreStatus.SCORED
    assert score.validity is Validity.VALID
    assert score.value == pytest.approx(1.0)


def test_partial_trajectory_scores_fraction_not_zero() -> None:
    example = _example(kind=UnitKind.TRAJECTORY, members=["a", "b", "c"], output=["x", None, "z"])
    score = _score(example)
    assert score.status is ScoreStatus.SCORED
    assert score.value == pytest.approx(2 / 3)


def test_call_unit_is_non_evaluable() -> None:
    score = _score(_example(kind=UnitKind.CALL, members=[], output=["x"]))
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None


def test_no_members_is_non_evaluable_not_zero() -> None:
    score = _score(_example(kind=UnitKind.SESSION, members=[], output=[]))
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None


def test_output_not_sequence_is_non_evaluable() -> None:
    score = _score(_example(kind=UnitKind.TRAJECTORY, members=["a"], output="not-a-list"))
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None


def test_all_null_output_is_non_evaluable_not_zero() -> None:
    """EG-P1-3: a trajectory where NO member produced output has no evidence to aggregate,
    so it is ``non_evaluable`` — never a misleading ``0.0`` (no-false-confidence)."""
    example = _example(kind=UnitKind.TRAJECTORY, members=["a", "b"], output=[None, None])
    score = _score(example)
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None


def test_single_member_all_null_session_is_non_evaluable() -> None:
    """EG-P1-3 degenerate: a single-call session whose one member produced no output is
    ``non_evaluable`` (0/1 must not render as ``0.0``)."""
    example = _example(kind=UnitKind.SESSION, members=["a"], output=[None])
    score = _score(example)
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None
