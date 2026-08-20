"""EGTS-M5C-1 — runner-attach seam proof (Route Proof, Trust Proof).

Proves the real product seam (ADR 0031, EG-H0-4): a configured optional lane runs in a real
``run_config`` run and its ``LaneResult`` lands in ``RunRecord.lane_results`` as a side channel —
while the ``Scorecard`` (verdict, authority, aggregates) stays byte-identical to a no-lane run.
The side channel carries no authority field; a disabled lane never runs; a misconfigured lane is a
blocked/skipped result, never a crash or a changed verdict. Negative control per the immutability
checker family (``tests/CLAUDE.md §12``).

Scenario id: ``m5c.runner_attach_seam`` (EG-M5C-1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import Scorecard
from evalglass.core.results import RunRecord
from evalglass.harness import runner as run_config_mod
from evalglass.harness.config import LaneConfig, RuntimeConfig
from evalglass.harness.lanes import LaneResult, LaneStatus
from evalglass.harness.runner import run_config
from tests.egts.checkers import CheckerError, check_scorecard_unchanged
from tests.scorecard_factory import (
    _matching_config,
    informational_record,
    record_with_export_lane,
)

_EXPORT_FILENAME = "scorecard.export.json"
_LANE_RESULT_KEYS = {"lane", "status", "report", "diagnostics"}


def _scorecard_bytes(record: RunRecord) -> str:
    return json.dumps(record.scorecard.to_dict(), sort_keys=True)


def test_m5c_seam_configured_lane_runs_as_side_channel(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.runs_as_side_channel — a configured SCORE_SINK lane runs in a real
    run, its result lands in lane_results, and the export artifact is written."""
    record = record_with_export_lane(tmp_path, export_dir="exports")
    assert len(record.lane_results) == 1
    entry = record.lane_results[0]
    assert entry["lane"] == "score-sink-export"
    assert entry["status"] == "ran"
    assert (tmp_path / "exports" / _EXPORT_FILENAME).is_file()


def test_m5c_seam_scorecard_byte_identical_with_and_without_lane(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.verdict_identity — the Scorecard is byte-identical whether or not a
    lane is configured: the seam adds rows to lane_results and nothing else."""
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()
    base = informational_record(no_lane)
    lane_run = record_with_export_lane(with_lane, export_dir="exports")
    assert _scorecard_bytes(lane_run) == _scorecard_bytes(base)
    assert base.lane_results == []
    assert lane_run.lane_results  # the only difference is the side channel


def test_m5c_seam_side_channel_carries_no_authority(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.authority_free — a lane_results entry has only the LaneResult keys;
    it never carries a score/value/verdict/authority/ci_should_fail field."""
    record = record_with_export_lane(tmp_path, export_dir="exports")
    entry = record.lane_results[0]
    assert set(entry) == _LANE_RESULT_KEYS
    for forbidden in ("score", "scores", "value", "verdict", "authority", "ci_should_fail"):
        assert forbidden not in entry


def test_m5c_seam_disabled_lane_does_not_run(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.disabled_no_run — a listed-but-disabled lane never runs."""
    cfg_data = _matching_config(tmp_path)
    cfg_data["lanes"] = [
        {"name": "score-sink-export", "enabled": False, "options": {"export_dir": "exports"}}
    ]
    record = run_config(RuntimeConfig.from_mapping(cfg_data), root=tmp_path)
    assert record.lane_results == []
    assert not (tmp_path / "exports").exists()


def test_m5c_seam_misconfigured_lane_is_fail_closed(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.fail_closed — an enabled lane with no destination is a skipped/
    blocked result (not a crash), and the verdict is untouched."""
    cfg_data = _matching_config(tmp_path)
    # enabled but no export_dir option → the export lane has no destination
    cfg_data["lanes"] = [{"name": "score-sink-export", "enabled": True, "options": {}}]
    record = run_config(RuntimeConfig.from_mapping(cfg_data), root=tmp_path)
    assert len(record.lane_results) == 1
    assert record.lane_results[0]["status"] in {"skipped", "blocked"}
    # the run still produced an honest verdict
    assert record.scorecard.verdict.verdict.value == "informational"


def test_negctl_seam_mutated_scorecard_fails_immutability(tmp_path: Path) -> None:
    """A lane that pretended to rewrite the verdict is caught by the immutability checker."""
    record = record_with_export_lane(tmp_path, export_dir="exports")
    before = dict(record.scorecard.to_dict())
    before["verdict"] = {"verdict": "pass"}  # pretend the lane changed the verdict
    with pytest.raises(CheckerError):
        check_scorecard_unchanged(record.scorecard, before)


class _RaisingSink:
    def __init__(self, **_: object) -> None:
        pass

    def export(self, scorecard: object) -> LaneResult:
        raise RuntimeError("simulated backend uploader failure")


class _MutatingSink:
    """A misbehaving lane that tries to mutate the Scorecard it is handed."""

    def __init__(self, **_: object) -> None:
        pass

    def export(self, scorecard: Scorecard) -> LaneResult:
        scorecard.metrics.clear()  # try to corrupt the run summary in place
        return LaneResult(lane="mutator", status=LaneStatus.RAN, report="ran")


class _StubRegistry:
    def __init__(self, factory: type) -> None:
        self._factory = factory

    def resolve(self, _name: str) -> type:
        return self._factory


def test_seam_export_failure_is_blocked_never_crashes_the_run(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.export_fail_closed — a lane whose export() raises is recorded as
    blocked; the exception never escapes the run."""
    lane_cfg = LaneConfig(name="score-sink-export", enabled=True)
    result = run_config_mod._run_score_sink_lane(
        _StubRegistry(_RaisingSink),  # type: ignore[arg-type]
        lane_cfg,
        informational_record(tmp_path).scorecard,
        tmp_path,
    )
    assert result.status is LaneStatus.BLOCKED
    assert result.diagnostics[0].code == "lane_export_failed"


def test_seam_lane_cannot_mutate_the_live_scorecard(tmp_path: Path) -> None:
    """m5c.runner_attach_seam.scorecard_isolation — a lane is handed a deep copy, so even a lane
    that mutates its argument cannot change the run's Scorecard (byte-identity holds)."""
    record = informational_record(tmp_path)
    before = record.scorecard.to_dict()
    assert record.scorecard.metrics, "the fixture run must have at least one metric to corrupt"
    run_config_mod._run_score_sink_lane(
        _StubRegistry(_MutatingSink),  # type: ignore[arg-type]
        LaneConfig(name="score-sink-export", enabled=True),
        record.scorecard,
        tmp_path,
    )
    assert record.scorecard.to_dict() == before  # the live Scorecard is untouched
