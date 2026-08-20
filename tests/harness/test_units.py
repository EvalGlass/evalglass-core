"""Harness unit selector (EG-M5-5 S1b): call-level unchanged; richer kinds group by trace."""

from __future__ import annotations

from evalglass.core import EvalUnit, Example, TraceEnvelope, UnitKind
from evalglass.harness.ports import TraceUnit
from evalglass.harness.prepare import example_from_trace
from evalglass.harness.units import select_units


def _tu(unit_id: str, trace_id: str, output: str) -> TraceUnit:
    env = TraceEnvelope.from_dict(
        {
            "trace_id": trace_id,
            "source": "trace_jsonl",
            "behavior": {"input": "q", "output": output},
            "data_policy": "permitted",
        }
    )
    unit = EvalUnit(unit_id=unit_id, kind=UnitKind.CALL, trace_id=trace_id)
    return TraceUnit(envelope=env, unit=unit)


def test_call_kind_is_unchanged_call_level_path() -> None:
    units = [_tu("c1", "t1", "a"), _tu("c2", "t2", "b")]
    selected = select_units(units, kind=UnitKind.CALL)
    expected = [example_from_trace(u) for u in units]
    assert [e.to_dict() for e in selected] == [e.to_dict() for e in expected]
    assert all(e.unit.kind is UnitKind.CALL for e in selected)


def test_trajectory_groups_calls_by_trace_id() -> None:
    units = [_tu("c1", "t1", "a"), _tu("c2", "t1", "b"), _tu("c3", "t2", "c")]
    selected = select_units(units, kind=UnitKind.TRAJECTORY)
    assert len(selected) == 2  # two trace_ids → two trajectories
    traj = next(e for e in selected if e.unit.trace_id == "t1")
    assert traj.unit.kind is UnitKind.TRAJECTORY
    assert traj.unit.members == ["c1", "c2"]
    assert traj.output == ["a", "b"]  # sequence of per-member outputs


def test_session_groups_calls() -> None:
    selected = select_units([_tu("c1", "s1", "a")], kind=UnitKind.SESSION)
    assert selected[0].unit.kind is UnitKind.SESSION
    assert selected[0].unit.members == ["c1"]


def test_aggregate_example_carries_no_raw_trace_shape() -> None:
    traj = select_units([_tu("c1", "t1", "a")], kind=UnitKind.TRAJECTORY)[0]
    assert isinstance(traj, Example)
    # output/input are vendor-neutral behavior values, not envelopes.
    assert traj.output == ["a"]
    assert not isinstance(traj.output[0], TraceEnvelope)
