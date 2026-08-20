"""Universal lane-conformance helpers (EG-AT4-2; alignment plan §5.0).

The five lane invariants — opt-in, removable, authority-free, hermetic-testable, fail-closed —
collected into reusable assertions so each lane proves the *same* contract instead of bespoke
per-lane checks. They wrap the EGTS lane checkers; a lane slice calls these rather than re-deriving
the rules. Test-only.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import evalglass
from evalglass.core import Scorecard
from evalglass.harness.lanes import LaneStatus, Maturity, built_in_lanes
from tests.egts.checkers import (
    check_lane_grants_no_authority,
    check_lane_imports_isolated,
    check_lane_metadata,
    check_scorecard_unchanged,
)

#: ``src/evalglass`` — the required-tier import closure the lane must stay out of.
SRC_ROOT = Path(evalglass.__file__).resolve().parent

#: Attributes a lane *result* must never carry (it informs, never decides).
_FORBIDDEN_RESULT_ATTRS = ("score", "scores", "value", "verdict", "authority", "ci_should_fail")


def assert_lane_is_opt_in_and_declared(lane_name: str) -> None:
    """(a) opt-in + metadata: declared, import-isolated, resolvable, conservatively mature."""
    registry = built_in_lanes()
    lane = registry.get(lane_name)
    check_lane_metadata(lane)
    check_lane_imports_isolated(SRC_ROOT, lane.module)
    assert callable(registry.resolve(lane_name)), f"{lane_name} does not resolve to a factory"
    # A lane never claims to be shipped-now; maturity stays conservative (AT3-2 / FS-SNAP-7).
    assert lane.maturity is not Maturity.NOW, f"{lane_name} claims maturity=now"


def assert_lane_result_is_authority_free(
    result: object, scorecard: Scorecard, before: Mapping[str, object]
) -> None:
    """(c) authority-free + verdict-immutable: no authority field, the scorecard is unchanged."""
    check_lane_grants_no_authority(result)
    check_scorecard_unchanged(scorecard, before)


def assert_lane_status_is_fail_closed(result: object) -> None:
    """(e) fail-closed: the outcome is a real ``LaneStatus``, never a fabricated score/verdict."""
    status = getattr(result, "status", None)
    assert isinstance(status, LaneStatus), f"lane result status is not a LaneStatus: {status!r}"
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], f"lane result carries forbidden attribute(s): {present}"


__all__ = [
    "SRC_ROOT",
    "assert_lane_is_opt_in_and_declared",
    "assert_lane_result_is_authority_free",
    "assert_lane_status_is_fail_closed",
]
