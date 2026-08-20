"""EGTS-M5-5 — richer EvalUnit (step/trajectory/session) + async observation proof.

Proves the end-to-end aggregate path through real product surfaces: the async-observation lane
**observes recorded behavior** → the harness selector groups it into a trajectory/session unit →
the `trajectory_shape` aggregate built-in scores it; the call-level path stays compatible; raw
shapes stay isolated in the TraceSource; and the async lane **never orchestrates** the host.
Run via ``egts test-lane richer-units``. Negative controls per checker (``tests/CLAUDE.md §12``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.adapters.async_observation import AsyncObservationTraceSource
from evalglass.core import EvidenceBundle, ScoreStatus, UnitKind, Validity
from evalglass.core.builtins import trajectory_shape
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType
from evalglass.harness.lanes import built_in_lanes
from evalglass.harness.ports import TraceUnit
from evalglass.harness.units import select_units
from tests.async_recording_factory import write_async_recording
from tests.egts.checkers import (
    CheckerError,
    check_lane_imports_isolated,
    check_lane_metadata,
    check_lane_observation_only,
)

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"
_SPANS = [
    {"trace_id": "t1", "span_id": "s1", "attributes": {"output.value": "a"}},
    {"trace_id": "t1", "span_id": "s2", "attributes": {"output.value": "b"}},
]


def _observed_units(tmp_path: Path) -> list[TraceUnit]:
    rec = write_async_recording(tmp_path, _SPANS)
    return AsyncObservationTraceSource(recording_path=rec, root=tmp_path).read().units


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


def test_m5b_async_observed_trajectory_scores_end_to_end(tmp_path: Path) -> None:
    """m5b.richer_units.async_to_trajectory_to_score — observe → select → aggregate score."""
    units = _observed_units(tmp_path)
    trajectories = select_units(units, kind=UnitKind.TRAJECTORY)
    assert len(trajectories) == 1
    traj = trajectories[0]
    assert traj.unit.kind is UnitKind.TRAJECTORY
    assert traj.unit.members == ["s1", "s2"]
    score = trajectory_shape.evaluate(
        traj, EvaluatorContext(spec=_spec(), params={}), EvidenceBundle()
    )
    assert score.status is ScoreStatus.SCORED
    assert score.validity is Validity.VALID
    assert score.value == pytest.approx(1.0)


def test_m5b_call_level_compatibility(tmp_path: Path) -> None:
    """m5b.richer_units.call_level_compatible — observed units still build call Examples."""
    calls = select_units(_observed_units(tmp_path), kind=UnitKind.CALL)
    assert [e.unit.kind for e in calls] == [UnitKind.CALL, UnitKind.CALL]
    assert [e.output for e in calls] == ["a", "b"]


def test_m5b_session_groups_trajectories(tmp_path: Path) -> None:
    sessions = select_units(_observed_units(tmp_path), kind=UnitKind.SESSION)
    assert sessions[0].unit.kind is UnitKind.SESSION
    assert sessions[0].unit.members == ["s1", "s2"]


def test_m5b_async_lane_is_observation_only(tmp_path: Path) -> None:
    """m5b.richer_units.async_observation_only — the lane reads; it never orchestrates the host."""
    check_lane_observation_only(_SRC, "evalglass.adapters.async_observation")


def test_negctl_orchestrating_lane_fails(tmp_path: Path) -> None:
    fake = tmp_path / "evalglass" / "adapters"
    fake.mkdir(parents=True)
    (fake / "bad_lane.py").write_text(
        "import subprocess\n\ndef read():\n    subprocess.run(['echo', 'hi'])\n", encoding="utf-8"
    )
    with pytest.raises(CheckerError):
        check_lane_observation_only(tmp_path / "evalglass", "evalglass.adapters.bad_lane")


def test_m5b_async_lane_declared_and_isolated() -> None:
    """m5b.richer_units.async_lane_deletable — declared metadata + required tier imports no lane."""
    lane = built_in_lanes().get("async-observation")
    check_lane_metadata(lane)
    check_lane_imports_isolated(_SRC, lane.module)


def test_m5b_async_lane_resolves(tmp_path: Path) -> None:
    assert built_in_lanes().resolve("async-observation") is AsyncObservationTraceSource
