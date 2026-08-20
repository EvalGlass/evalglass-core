"""FS-DEL — deletion-invariance + the runner-attach seam (EG-AT1-4; seam landed EG-H0-4).

An optional lane may *never* change the product verdict. Two guards enforce that:

* **The seam exists and folds evidence, never a decision (FS-DEL-3).** ``runner.py``
  now resolves configured lanes through the framework and folds each ``LaneResult``
  into ``RunRecord.lane_results`` — a side channel. A configured lane runs in a real
  run yet leaves the verdict byte-identical to a no-lane run. (The dataflow guard that
  a lane result never reaches verdict/authority/Scorecard construction lives in
  ``test_lane_attach_seam.py``.)
* **A lane is verdict-preserving (FS-DEL-1).** Running a real one-way lane (the
  score-sink export) over a Scorecard leaves the typed ``VerdictPayload``
  byte-identical, and the payload is a frozen dataclass a lane cannot mutate.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from evalglass.core.results import RunRecord
from evalglass.core.verdict import Verdict
from evalglass.harness.lanes import LaneStatus, built_in_lanes
from tests.scorecard_factory import informational_record, record_with_export_lane

_EXPORT_FILENAME = "scorecard.export.json"

_RUNNER = Path(__file__).resolve().parents[2] / "src" / "evalglass" / "harness" / "runner.py"


def _verdict_bytes(record: RunRecord) -> str:
    return json.dumps(record.scorecard.verdict.to_dict(), sort_keys=True)


def test_post_seam_lane_runs_as_side_channel_without_touching_verdict(tmp_path: Path) -> None:
    """[FS-DEL-3, post-seam] A configured lane runs and lands in ``lane_results``, but the
    verdict is byte-identical to a no-lane run — the seam folds evidence, never a decision."""
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()

    baseline = _verdict_bytes(informational_record(no_lane))
    record = record_with_export_lane(with_lane, export_dir="exports")

    # The lane actually RAN and is recorded only as a side channel...
    assert [r["status"] for r in record.lane_results] == [LaneStatus.RAN.value]
    assert record.lane_results[0]["lane"] == "score-sink-export"
    assert (with_lane / "exports" / _EXPORT_FILENAME).is_file()
    # ...and it left the verdict byte-identical to the no-lane run.
    assert _verdict_bytes(record) == baseline


def test_post_seam_runner_resolves_lanes_through_the_framework() -> None:
    """The seam now exists: ``runner.py`` resolves lanes via the framework (absent pre-seam)."""
    assert "built_in_lanes" in _RUNNER.read_text(encoding="utf-8")


def test_verdict_identical_whether_lane_framework_loaded(tmp_path: Path) -> None:
    """A run's verdict is byte-identical whether the lane registry is built or not."""
    run_a = tmp_path / "a"
    run_a.mkdir()
    run_b = tmp_path / "b"
    run_b.mkdir()
    before = _verdict_bytes(informational_record(run_a))
    registry = built_in_lanes()  # build + register the unconfigured lanes
    after = _verdict_bytes(informational_record(run_b))
    assert before == after
    assert len(registry.lanes()) == 9  # the framework loaded, yet changed nothing


def test_specificity_readonly_lane_preserves_verdict(tmp_path: Path) -> None:
    """A real one-way lane (score-sink export) leaves the VerdictPayload byte-identical."""
    record = informational_record(tmp_path)
    before = _verdict_bytes(record)
    factory = built_in_lanes().resolve("score-sink-export")
    sink = factory(export_dir="export", root=tmp_path)
    result = sink.export(record.scorecard)
    # The lane must actually RUN — a blocked/skipped lane would prove nothing.
    assert result.status is LaneStatus.RAN
    assert (tmp_path / "export" / _EXPORT_FILENAME).is_file()
    assert _verdict_bytes(record) == before  # the sink consumed, never mutated


def test_sensitivity_mutating_lane_breaks_identity(tmp_path: Path) -> None:
    """Byte comparison detects a lane that altered the verdict — the guard can fail."""
    record = informational_record(tmp_path)
    original = _verdict_bytes(record)
    tampered = dict(record.scorecard.verdict.to_dict())
    tampered["verdict"] = Verdict.PASS.value
    tampered["ci_should_fail"] = False
    assert json.dumps(tampered, sort_keys=True) != original


def test_verdict_scalar_fields_are_frozen(tmp_path: Path) -> None:
    """The verdict-defining scalars cannot be reassigned (frozen dataclass)."""
    payload = informational_record(tmp_path).scorecard.verdict
    with pytest.raises(dataclasses.FrozenInstanceError):
        payload.verdict = Verdict.PASS  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        payload.ci_should_fail = True  # type: ignore[misc]


def test_verdict_to_dict_is_a_defensive_copy(tmp_path: Path) -> None:
    """to_dict() copies the gate lists, so the FS-DEL byte snapshot resists mutation.

    The frozen dataclass does not deep-freeze its list fields — ``passing_gates`` can be
    mutated in place. The deletion proof is sound anyway because ``to_dict()`` returns
    independent copies in both directions: a captured snapshot cannot be changed by a
    later in-place mutation of the payload, and mutating a returned dict never reaches
    back into the payload.
    """
    payload = informational_record(tmp_path).scorecard.verdict
    returned = payload.to_dict()
    returned["passing_gates"].append("injected")
    assert "injected" not in payload.to_dict()["passing_gates"]

    captured = json.dumps(payload.to_dict(), sort_keys=True)
    payload.passing_gates.append("injected")  # in-place mutation IS possible
    assert "injected" not in json.loads(captured)["passing_gates"]  # the snapshot is immune
