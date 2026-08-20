"""Layer-1 unit tests for the ScoreSink export lane (EG-M5-4; ADR 0019)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.score_sink_export import FileScorecardExportSink, ScorecardExportSink
from evalglass.harness.lanes import LaneStatus, MissingPrerequisite
from tests.scorecard_factory import informational_scorecard as _scorecard


def test_no_destination_skips(tmp_path: Path) -> None:
    with pytest.raises(MissingPrerequisite):
        FileScorecardExportSink(export_dir=None, root=tmp_path)


def test_satisfies_export_protocol(tmp_path: Path) -> None:
    assert isinstance(FileScorecardExportSink(export_dir="out", root=tmp_path), ScorecardExportSink)


def test_export_writes_immutable_scorecard_json(tmp_path: Path) -> None:
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    sink = FileScorecardExportSink(export_dir="export", root=tmp_path)
    result = sink.export(scorecard)
    assert result.status is LaneStatus.RAN
    # The Scorecard is consumed read-only — unchanged after export.
    assert scorecard.to_dict() == before
    # The exported file is a faithful copy of the Scorecard.
    written = json.loads((tmp_path / "export" / "scorecard.export.json").read_text())
    assert written == before


def test_export_result_grants_no_authority(tmp_path: Path) -> None:
    result = FileScorecardExportSink(export_dir="export", root=tmp_path).export(
        _scorecard(tmp_path)
    )
    for forbidden in ("score", "verdict", "authority", "ci_should_fail"):
        assert not hasattr(result, forbidden)


def test_export_failure_is_blocked_diagnostic_not_a_changed_verdict(tmp_path: Path) -> None:
    scorecard = _scorecard(tmp_path)
    verdict_before = scorecard.verdict.verdict
    # Make mkdir fail: a file occupies the parent path component.
    (tmp_path / "occupied").write_text("x", encoding="utf-8")
    sink = FileScorecardExportSink(export_dir="occupied/sub", root=tmp_path)
    result = sink.export(scorecard)
    assert result.status is LaneStatus.BLOCKED
    assert result.diagnostics[0].code == "score_sink_export_failed"
    # The core verdict is untouched and still readable — the failure did not hide it.
    assert scorecard.verdict.verdict == verdict_before
