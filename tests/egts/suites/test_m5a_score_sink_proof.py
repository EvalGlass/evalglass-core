"""EGTS-M5-4 — ScoreSink export lane proof (Integration Proof, Trust Proof).

Proves the real `FileScorecardExportSink`: it consumes an **immutable** Scorecard (the verdict /
authority / CI exit are never mutated), a sink **failure** is a diagnostic that does **not** hide
the core verdict, the lane grants no authority and is import-isolated (deletable), and deleting the
lane leaves the local Markdown/JSON reports intact. Run via ``egts test-lane score-sink``. Negative
controls per checker (``tests/CLAUDE.md §12``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.adapters.score_sink_export import FileScorecardExportSink
from evalglass.harness.lanes import LaneStatus, built_in_lanes
from evalglass.harness.report import MarkdownScoreSink
from tests.egts.checkers import (
    CheckerError,
    check_lane_grants_no_authority,
    check_lane_imports_isolated,
    check_lane_metadata,
    check_scorecard_unchanged,
)
from tests.scorecard_factory import informational_scorecard as _scorecard

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"


def test_m5a_score_sink_consumes_immutable_scorecard(tmp_path: Path) -> None:
    """m5a.score_sink.consumes_immutable_scorecard — export leaves the Scorecard byte-identical."""
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    result = FileScorecardExportSink(export_dir="export", root=tmp_path).export(scorecard)
    check_scorecard_unchanged(scorecard, before)
    check_lane_grants_no_authority(result)
    assert result.status is LaneStatus.RAN


def test_negctl_mutated_scorecard_fails_immutability(tmp_path: Path) -> None:
    scorecard = _scorecard(tmp_path)
    before = dict(scorecard.to_dict())
    before["verdict"] = {"verdict": "pass"}  # pretend the sink rewrote the verdict
    with pytest.raises(CheckerError):
        check_scorecard_unchanged(scorecard, before)


def test_m5a_score_sink_failure_does_not_hide_verdict(tmp_path: Path) -> None:
    """m5a.score_sink.failure_does_not_hide_verdict — a failed publish is a diagnostic only."""
    scorecard = _scorecard(tmp_path)
    verdict_before = scorecard.verdict.verdict
    (tmp_path / "occupied").write_text("x", encoding="utf-8")
    result = FileScorecardExportSink(export_dir="occupied/sub", root=tmp_path).export(scorecard)
    assert result.status is LaneStatus.BLOCKED
    assert result.diagnostics[0].code == "score_sink_export_failed"
    assert scorecard.verdict.verdict == verdict_before  # verdict untouched


def test_m5a_score_sink_deletion_leaves_local_reports(tmp_path: Path) -> None:
    """m5a.score_sink.deletion_leaves_local_reports — local Markdown render is independent."""
    scorecard = _scorecard(tmp_path)
    rendered = MarkdownScoreSink().render(scorecard)
    assert "# EvalGlass Scorecard" in rendered  # local report works without the export lane


def test_m5a_score_sink_lane_is_declared_and_isolated() -> None:
    """m5a.score_sink.declared_and_deletable — declared metadata + no required import of lane."""
    lane = built_in_lanes().get("score-sink-export")
    check_lane_metadata(lane)
    check_lane_imports_isolated(_SRC, lane.module)


def test_m5a_score_sink_resolves_via_registry() -> None:
    assert built_in_lanes().resolve("score-sink-export") is FileScorecardExportSink
