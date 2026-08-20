"""Core richer-EvalUnit contract (EG-M5-5 S1a; ADR 0020).

Step/trajectory/session units declare their constituent sub-units via ``members`` (additive); the
call-level shape is unchanged (no ``members`` key), serialization is fail-closed, and ``ScoreBatch``
is the aggregate-result contract an aggregate evaluator emits.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core import (
    ContractError,
    EvalUnit,
    Score,
    ScoreBatch,
    ScoreStatus,
    UnitKind,
    Validity,
)


def test_trajectory_unit_round_trips_with_members() -> None:
    unit = EvalUnit(
        unit_id="traj-1",
        kind=UnitKind.TRAJECTORY,
        trace_id="t1",
        members=["call-1", "call-2", "call-3"],
        locator={"span": "0..3"},
    )
    payload = unit.to_dict()
    assert payload["members"] == ["call-1", "call-2", "call-3"]
    assert EvalUnit.from_dict(payload) == unit
    assert json.loads(json.dumps(payload))["members"][0] == "call-1"


def test_session_unit_snapshot() -> None:
    unit = EvalUnit(
        unit_id="sess-1", kind=UnitKind.SESSION, trace_id="t1", members=["traj-1", "traj-2"]
    )
    assert unit.to_dict() == {
        "unit_id": "sess-1",
        "kind": "session",
        "trace_id": "t1",
        "members": ["traj-1", "traj-2"],
    }


def test_call_level_unit_is_unchanged_no_members_key() -> None:
    # The call-level MVP shape must not gain a key — existing snapshots stay valid.
    call = EvalUnit(unit_id="c1", kind=UnitKind.CALL, trace_id="t1")
    assert "members" not in call.to_dict()
    assert call.to_dict() == {"unit_id": "c1", "kind": "call", "trace_id": "t1"}


def test_members_must_be_a_list_of_strings() -> None:
    base = {"unit_id": "u", "kind": "trajectory", "trace_id": "t"}
    with pytest.raises(ContractError):
        EvalUnit.from_dict({**base, "members": "not-a-list"})
    with pytest.raises(ContractError):
        EvalUnit.from_dict({**base, "members": [1, 2]})


def test_absent_members_defaults_empty() -> None:
    unit = EvalUnit.from_dict({"unit_id": "u", "kind": "step", "trace_id": "t"})
    assert unit.members == []


def test_score_batch_is_the_aggregate_result_contract() -> None:
    # An aggregate evaluator over a trajectory emits a ScoreBatch of related scores.
    batch = ScoreBatch(
        evaluator="trajectory_shape@1",
        scores=[
            Score(
                metric="trajectory.step_count",
                value=3.0,
                status=ScoreStatus.SCORED,
                validity=Validity.VALID,
                evaluator_version="trajectory_shape@1",
            ),
            Score(
                metric="trajectory.has_output",
                value=1.0,
                status=ScoreStatus.SCORED,
                validity=Validity.VALID,
                evaluator_version="trajectory_shape@1",
            ),
        ],
    )
    assert ScoreBatch.from_dict(batch.to_dict()) == batch
    assert len(batch.to_dict()["scores"]) == 2
