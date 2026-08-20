"""EG-AT4-2 — every built-in lane satisfies the universal conformance contract (§5.0).

Drives the reusable lane-conformance helpers over the four shipped lanes, and proves (via negative
controls) that each helper actually fires on a non-conforming lane / result.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from evalglass.harness.lanes import LaneError, LaneResult, LaneStatus, built_in_lanes
from tests.egts.checkers import CheckerError
from tests.egts.lane_conformance import (
    assert_lane_is_opt_in_and_declared,
    assert_lane_result_is_authority_free,
    assert_lane_status_is_fail_closed,
)
from tests.fixtures.sinks import make_capture_sink
from tests.scorecard_factory import informational_scorecard

_LANE_NAMES = built_in_lanes().names()


def test_at_least_the_four_built_in_lanes_exist() -> None:
    assert set(_LANE_NAMES) >= {
        "live-judge",
        "trace-backend",
        "score-sink-export",
        "async-observation",
    }


@pytest.mark.parametrize("lane_name", _LANE_NAMES)
def test_every_built_in_lane_is_opt_in_and_declared(lane_name: str) -> None:
    assert_lane_is_opt_in_and_declared(lane_name)


def test_lane_status_helper_accepts_a_real_lane_result() -> None:
    assert_lane_status_is_fail_closed(LaneResult(lane="x", status=LaneStatus.SKIPPED, report="ok"))


def test_authority_free_helper_accepts_a_real_one_way_lane(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    before = scorecard.to_dict()
    result = make_capture_sink().export(scorecard)
    assert_lane_result_is_authority_free(result, scorecard, before)


def test_negctl_authority_free_helper_fires_on_a_mutated_scorecard(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    tampered_before = {**scorecard.to_dict(), "verdict": {"verdict": "pass"}}
    result = make_capture_sink().export(scorecard)  # a clean lane result...
    with pytest.raises(CheckerError):  # ...but the scorecard-immutability half must still fire
        assert_lane_result_is_authority_free(result, scorecard, tampered_before)


def test_negctl_authority_free_helper_fires_on_a_forged_result(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    before = scorecard.to_dict()

    @dataclasses.dataclass
    class _Forged:
        status: LaneStatus = LaneStatus.RAN
        ci_should_fail: bool = False  # a lane result must never carry ci_should_fail

    with pytest.raises(CheckerError):
        assert_lane_result_is_authority_free(_Forged(), scorecard, before)


def test_negctl_opt_in_helper_fires_on_an_unknown_lane() -> None:
    with pytest.raises(LaneError):
        assert_lane_is_opt_in_and_declared("does-not-exist")


def test_negctl_fail_closed_helper_fires_on_an_authority_bearing_result() -> None:
    @dataclasses.dataclass
    class _Authoritative:
        status: LaneStatus = LaneStatus.RAN
        verdict: str = "pass"  # a lane result must never carry a verdict

    with pytest.raises(AssertionError):
        assert_lane_status_is_fail_closed(_Authoritative())


def test_negctl_no_authority_checker_fires_on_a_forged_result() -> None:
    @dataclasses.dataclass
    class _Forged:
        status: LaneStatus = LaneStatus.RAN
        ci_should_fail: bool = False

    from tests.egts.checkers import check_lane_grants_no_authority

    with pytest.raises(CheckerError):
        check_lane_grants_no_authority(_Forged())
