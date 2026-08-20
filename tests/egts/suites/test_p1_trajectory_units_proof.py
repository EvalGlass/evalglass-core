"""EGTS-P1 — config-reachable trajectory/session unit proof (EG-P1; ADR 0045).

Re-proves, through the **real product surface** ``load_config`` → ``run_config`` (not
``select_units`` directly, which ``test_m5b_richer_units_proof.py`` already covers), that a
config-driven trace route declaring ``unit: trajectory`` (or ``session``) grades the aggregate
slice: the harness collapses a trace's call-level units into one aggregate Example, the
``trajectory_shape@1`` built-in scores it, and the typed ``Scorecard`` carries an honest
``informational`` verdict. Every negative control (tests/CLAUDE.md §12) proves the checker
family is sensitive: the CALL path stays per-call; a forbidden member blocks the aggregate's
egress; and a degenerate trajectory is ``non_evaluable``, never a fabricated ``0.0``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import RunRecord, ScoreStatus, UnitKind, Verdict
from evalglass.harness.config import TraceConfig
from evalglass.harness.loader import load_config
from evalglass.harness.runner import _load_trace_units, run_config
from tests.egts.checkers import check_verdict
from tests.egts.workspace import RuntimeWorkspace, make_workspace

_TRAJECTORY_METRIC = """
  - name: trajectory.shape
    evaluator_ref: trajectory_shape@1
    lens: non_reference
    granularity: trajectory
    score_type: continuous
    score_range: [0.0, 1.0]
    direction: higher_is_better
"""

#: A two-call trace sharing one ``trace_id`` — a minimal multi-step "trajectory".
_TWO_CALL_TRACE = (
    json.dumps({"trace_id": "t1", "behavior": {"input": "q1", "output": "a"}})
    + "\n"
    + json.dumps({"trace_id": "t1", "behavior": {"input": "q2", "output": "b"}})
    + "\n"
)


def _cfg(unit: str) -> str:
    """A ``traces:`` config at the given ``unit:`` kind, scoring the aggregate built-in."""
    return f"traces:\n  - path: traces/t.jsonl\n    unit: {unit}\nmetrics:{_TRAJECTORY_METRIC}"


def _run(ws: RuntimeWorkspace) -> RunRecord:
    return run_config(load_config(ws.config_path), root=ws.root)


def _trajectory_ws(tmp_path: Path, fixture_id: str, *, unit: str) -> RuntimeWorkspace:
    return make_workspace(
        tmp_path, fixture_id, config=_cfg(unit), traces={"t.jsonl": _TWO_CALL_TRACE}
    )


def test_p1_config_trajectory_scores_aggregate_informational(tmp_path: Path) -> None:
    """p1.trajectory.config_reachable — ``unit: trajectory`` → one honest informational row."""
    record = _run(_trajectory_ws(tmp_path, "p1-traj", unit="trajectory"))
    # Typed artifacts first: exactly one aggregate score, from the declared aggregate built-in.
    assert len(record.scores) == 1
    score = record.scores[0]
    assert score.evaluator_version == "trajectory_shape@1"
    assert score.unit_id == "trajectory:t1"
    assert score.status is ScoreStatus.SCORED
    assert score.value == pytest.approx(1.0)  # both members produced output
    # The verdict is the product's, checked (never recomputed by EGTS).
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)
    assert record.scorecard.verdict.ci_should_fail is False


def test_p1_config_session_scores_aggregate(tmp_path: Path) -> None:
    """p1.session.config_reachable — ``unit: session`` reaches the same aggregate path."""
    record = _run(_trajectory_ws(tmp_path, "p1-session", unit="session"))
    assert len(record.scores) == 1
    assert record.scores[0].unit_id == "session:t1"
    assert record.scores[0].evaluator_version == "trajectory_shape@1"
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)


def test_negctl_call_unit_yields_per_call_scores(tmp_path: Path) -> None:
    """Negative control (order/shape): the same trace at ``unit: call`` grades each call."""
    record = _run(_trajectory_ws(tmp_path, "p1-call", unit="call"))
    # Two calls → the aggregate built-in is non_evaluable per-call, never one aggregate score.
    assert len(record.scores) == 2
    assert {s.unit_id for s in record.scores} == {"traces/t.jsonl#1", "traces/t.jsonl#2"}
    assert all(s.status is ScoreStatus.NON_EVALUABLE for s in record.scores)


def test_negctl_forbidden_member_blocks_aggregate_egress(tmp_path: Path) -> None:
    """Negative control (egress): one forbidden member ⇒ the whole aggregate is not egress-OK.

    Exercises the production egress resolver ``_load_trace_units`` (the exact function the runner
    calls) — an aggregate is egress-OK iff *every* member is (worst-of-members, fail-closed).
    """
    from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource

    ws = make_workspace(
        tmp_path,
        "p1-egress",
        config=_cfg("trajectory"),
        traces={
            "t.jsonl": (
                json.dumps(
                    {"trace_id": "t1", "behavior": {"output": "a"}, "data_policy": "permitted"}
                )
                + "\n"
                + json.dumps(
                    {"trace_id": "t1", "behavior": {"output": "b"}, "data_policy": "forbidden"}
                )
                + "\n"
            )
        },
    )
    units = (
        LocalJsonlTraceSource(TraceConfig(path="traces/t.jsonl", name="t"), ws.root).read().units
    )
    pairs = _load_trace_units(units, UnitKind.TRAJECTORY)
    assert [ok for _, ok in pairs] == [False]  # aggregate blocked by its forbidden member


def test_negctl_degenerate_trajectory_is_non_evaluable_not_zero(tmp_path: Path) -> None:
    """Negative control (honesty): an all-``None``-output trajectory is non_evaluable, never 0.0."""
    ws = make_workspace(
        tmp_path,
        "p1-degenerate",
        config=_cfg("trajectory"),
        traces={
            "t.jsonl": (
                json.dumps({"trace_id": "t1", "behavior": {"input": "q1"}})
                + "\n"
                + json.dumps({"trace_id": "t1", "behavior": {"input": "q2"}})
                + "\n"
            )
        },
    )
    record = _run(ws)
    assert len(record.scores) == 1
    score = record.scores[0]
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None  # the forbidden 0.0 collapse never happens
