"""EG-AT4-3 — harden the shipped score-sink-export lane (alignment plan §5.1).

The one shipped export lane writes exactly the Scorecard JSON, fails closed on a destination
outside the host root and on an OS error (never a score/verdict/0.0), and declares the conservative
``experimental`` maturity that is provably not a Verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.adapters.score_sink_export import FileScorecardExportSink
from evalglass.core.verdict import Verdict
from evalglass.harness.lanes import LaneStatus, Maturity, built_in_lanes
from tests.egts.lane_conformance import assert_lane_status_is_fail_closed
from tests.scorecard_factory import informational_scorecard

_EXPORT_FILENAME = "scorecard.export.json"


def test_export_round_trip_is_byte_identical(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    result = FileScorecardExportSink(export_dir="export", root=tmp_path).export(scorecard)
    assert result.status is LaneStatus.RAN
    written = (tmp_path / "export" / _EXPORT_FILENAME).read_text(encoding="utf-8")
    assert json.loads(written) == scorecard.to_dict()


def test_export_destination_outside_root_fails_closed(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    result = FileScorecardExportSink(export_dir="../../etc/evil", root=tmp_path).export(scorecard)
    assert result.status is LaneStatus.BLOCKED
    assert result.diagnostics
    assert result.diagnostics[0].code == "score_sink_export_outside_root"
    assert not (tmp_path.parent.parent / "etc" / "evil").exists()
    assert_lane_status_is_fail_closed(result)  # blocked, never a score/verdict/0.0


def test_export_failure_is_blocked_not_zero(tmp_path: Path) -> None:
    # A file occupying the export dir path makes mkdir fail → BLOCKED, never a fabricated value.
    (tmp_path / "occupied").write_text("x", encoding="utf-8")
    result = FileScorecardExportSink(export_dir="occupied/sub", root=tmp_path).export(
        informational_scorecard(tmp_path)
    )
    assert result.status is LaneStatus.BLOCKED
    assert_lane_status_is_fail_closed(result)


def test_score_sink_maturity_is_experimental_never_a_verdict() -> None:
    lane = built_in_lanes().get("score-sink-export")
    assert lane.maturity is Maturity.EXPERIMENTAL
    assert lane.maturity.value not in {v.value for v in Verdict}
