"""EG-AT3-2 — ExtensionLane.maturity capability-status metadata (alignment plan §5.9).

``maturity`` is the one place the public-site capability taxonomy
(now/next/planned/experimental) enters the product, as additive ``ExtensionLane``
metadata (ADR 0029). It round-trips, fails closed on an unknown token, defaults to
the conservative end, and is never read by the verdict / exit path.
"""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.core.verdict import Verdict
from evalglass.harness.exits import _VERDICT_CLASS
from evalglass.harness.lanes import (
    ExtensionLane,
    LaneError,
    LanePort,
    LaneResult,
    LaneStatus,
    Maturity,
    built_in_lanes,
)
from tests.egts.checkers import check_lane_grants_no_authority


def _lane(**overrides: Any) -> ExtensionLane:
    base: dict[str, Any] = {
        "name": "x",
        "purpose": "p",
        "port": LanePort.SCORE_SINK,
        "module": "a.b",
        "factory": "F",
        "boundary": "b",
        "deletion_rule": "d",
    }
    base.update(overrides)
    return ExtensionLane(**base)


def test_extension_lane_maturity_round_trips() -> None:
    lane = _lane(maturity=Maturity.NEXT)
    assert lane.to_dict()["maturity"] == "next"
    assert ExtensionLane.from_dict(lane.to_dict()) == lane
    # A plain string coerces to the enum.
    assert _lane(maturity="planned").maturity is Maturity.PLANNED
    # Every built-in lane round-trips with its maturity intact.
    for built in built_in_lanes().lanes():
        assert ExtensionLane.from_dict(built.to_dict()) == built


_INVALID_MATURITY: list[Any] = ["approved", "validated", "gating", "", "NOW", 1, None]


@pytest.mark.parametrize("bad", _INVALID_MATURITY)
def test_invalid_maturity_token_fails_with_lane_error(bad: Any) -> None:
    with pytest.raises(LaneError):
        _lane(maturity=bad)
    if isinstance(bad, str):
        with pytest.raises(LaneError):
            ExtensionLane.from_dict({**_lane().to_dict(), "maturity": bad})


def test_missing_maturity_defaults_to_experimental_never_now() -> None:
    assert _lane().maturity is Maturity.EXPERIMENTAL
    # from_dict without a maturity key defaults conservatively.
    without = _lane().to_dict()
    del without["maturity"]
    assert ExtensionLane.from_dict(without).maturity is Maturity.EXPERIMENTAL
    # The default is never the shipped end, and no built-in lane claims "now".
    assert _lane().maturity is not Maturity.NOW
    assert all(lane.maturity is not Maturity.NOW for lane in built_in_lanes().lanes())


def test_maturity_does_not_feed_ci_should_fail_or_verdict() -> None:
    """``maturity`` is inert metadata — a run outcome never carries or branches on it."""
    result = LaneResult(lane="x", status=LaneStatus.RAN, report="ok")
    assert not hasattr(result, "maturity")
    check_lane_grants_no_authority(result)
    # The exit/verdict mapping is keyed only on Verdict, never on a Maturity.
    assert set(_VERDICT_CLASS) == set(Verdict)
    # And the capability tokens are disjoint from the run-outcome enums.
    maturity_values = {m.value for m in Maturity}
    assert maturity_values.isdisjoint({v.value for v in Verdict})
    assert maturity_values.isdisjoint({s.value for s in LaneStatus})
