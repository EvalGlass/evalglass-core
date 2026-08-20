"""Governance 1D — sinks and handoffs cannot launder authority back in (EG-AT2-4).

Source: alignment test plan §6 Part 1D.

A re-admitted sink/handoff is a *one-way* optional output: it renders or exports an
immutable Scorecard and returns an authority-free ``LaneResult``. It can never
approve, gate, certify, promote, tune, edit, or write back host truth. The hosted
dashboard sink (EG-AT4-4) and prompt-optimizer handoff (EG-AT4-5) are not shipped
yet, so this slice proves the **generic governance law** over the surfaces that *do*
exist — ``LaneResult`` and the shipped one-way ``FileScorecardExportSink`` — which is
exactly the contract those future lanes must satisfy.

Pure, hermetic unit tests in a new file; the frozen canary ``test_governance.py``
stays byte-stable (AT1 FS-META).
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from evalglass.adapters.score_sink_export import FileScorecardExportSink, ScorecardExportSink
from evalglass.core import Scorecard
from evalglass.harness.lanes import LaneResult, LaneStatus
from tests.egts.checkers import (
    CheckerError,
    check_lane_grants_no_authority,
    check_scorecard_unchanged,
)
from tests.fixtures.sinks import make_capture_sink
from tests.scorecard_factory import informational_scorecard

# Authority/feedback/edit verbs a one-way output must never expose as a public method.
_FORBIDDEN_VERB = re.compile(
    r"approve|gate|certify|validate|promote|tune|edit|writeback|feedback|mutate", re.IGNORECASE
)


def _public_callables(obj: object) -> list[str]:
    return [n for n in dir(obj) if not n.startswith("_") and callable(getattr(obj, n, None))]


def test_lane_result_fields_are_exactly_the_four() -> None:
    """A ``LaneResult`` carries only status/report/diagnostics — never a verdict or score."""
    field_names = {f.name for f in dataclasses.fields(LaneResult)}
    assert field_names == {"lane", "status", "report", "diagnostics"}


def test_lane_result_grants_no_authority_with_negative_control() -> None:
    """A real ``LaneResult`` is authority-free; a forged result with a verdict is rejected."""
    check_lane_grants_no_authority(LaneResult(lane="x", status=LaneStatus.RAN, report="ok"))

    @dataclasses.dataclass
    class _Authoritative:
        status: str = "ran"
        verdict: str = "pass"  # a lane result must never carry a verdict

    with pytest.raises(CheckerError):
        check_lane_grants_no_authority(_Authoritative())


def test_one_way_export_sink_exposes_export_and_nothing_else(tmp_path: Path) -> None:
    """The shipped one-way sink's public API is *exactly* ``export`` — nothing else.

    This is the contract the (deferred) hosted-dashboard sink and prompt-optimizer
    handoff must satisfy: a one-way export with no second public method — so no
    ``upload``, ``write_back``, ``promote``, ``tune``, or any other path to mutate
    host truth or feed authority back in. An exact set (rather than a verb denylist)
    catches both ``writeBack`` and the snake_case ``write_back`` spelling.
    """
    sinks: list[object] = [
        FileScorecardExportSink(export_dir="export", root=tmp_path),
        make_capture_sink(),
    ]
    for sink in sinks:
        assert set(_public_callables(sink)) == {"export"}, (
            f"{type(sink).__name__} public API is not export-only: {_public_callables(sink)}"
        )
    # The protocol declares the one-way export entry point and no authority/feedback verb.
    protocol_methods = _public_callables(ScorecardExportSink)
    assert "export" in protocol_methods
    assert [m for m in protocol_methods if _FORBIDDEN_VERB.search(m)] == []


@pytest.mark.adapter_conformance
def test_successful_export_leaves_the_scorecard_unchanged(tmp_path: Path) -> None:
    """A one-way export renders the Scorecard verbatim and never mutates it."""
    scorecard: Scorecard = informational_scorecard(tmp_path)
    before = scorecard.to_dict()
    sink = make_capture_sink()
    result = sink.export(scorecard)
    check_scorecard_unchanged(scorecard, before)
    check_lane_grants_no_authority(result)
    assert sink.captured[0] == json.dumps(scorecard.to_dict(), sort_keys=True).encode("utf-8")


@pytest.mark.adapter_conformance
def test_real_sink_failure_path_does_not_change_verdict_or_scores(tmp_path: Path) -> None:
    """The *shipped* sink's failure path is a diagnostic only — it never mutates the Scorecard.

    Drive ``FileScorecardExportSink`` into its real blocked path (the export dir is
    occupied by a file) and prove it returns a ``BLOCKED`` ``LaneResult`` while leaving
    the verdict and every score value byte-identical.
    """
    scorecard = informational_scorecard(tmp_path)
    before = scorecard.to_dict()
    verdict_before = scorecard.verdict.verdict
    (tmp_path / "occupied").write_text("x", encoding="utf-8")  # block the export dir

    result = FileScorecardExportSink(export_dir="occupied/sub", root=tmp_path).export(scorecard)

    assert result.status is LaneStatus.BLOCKED
    check_lane_grants_no_authority(result)
    check_scorecard_unchanged(scorecard, before)
    assert scorecard.verdict.verdict == verdict_before
