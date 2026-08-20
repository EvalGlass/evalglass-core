"""EGP-P2-3: the committed gallery examples are honest regression fixtures.

The gallery ships real, regenerated artifacts (not hand-edited). These assertions pin the trust
posture of the committed Scorecards so a future change cannot quietly turn a gallery example into a
fake green: every committed example is `informational`, and the judge-calibration example proves the
calibration prerequisite — a judge metric is *scored* yet **cannot gate** while uncalibrated.
"""

from __future__ import annotations

import json
from typing import Any

from tests.plugin.conftest import REPO_ROOT

_GALLERY = REPO_ROOT / "examples"


def _scorecard(example: str, run: str) -> dict[str, Any]:
    path = _GALLERY / example / "evals" / "reports" / run / "scorecard.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _runrecord(example: str, run: str) -> dict[str, Any]:
    path = _GALLERY / example / "evals" / "reports" / run / "runrecord.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_groundedness_example_is_informational() -> None:
    verdict = _scorecard("groundedness", "groundedness")["verdict"]
    assert verdict["verdict"] == "informational"
    assert verdict["ci_should_fail"] is False


def test_judge_calibration_example_verdict_is_informational() -> None:
    verdict = _scorecard("judge-calibration", "judge-calibration")["verdict"]
    assert verdict["verdict"] == "informational"
    assert verdict["ci_should_fail"] is False


def test_judge_is_scored_but_cannot_gate_while_uncalibrated() -> None:
    """The calibration prerequisite, demonstrated on a real artifact."""
    sc = _scorecard("judge-calibration", "judge-calibration")
    authority = sc["authority"]["faithfulness"]
    assert authority["level"] == "informational"  # not gating, despite the config asking
    assert authority["can_gate"] is False
    # yet the judge produced real, scored values (not blocked, not 0.0-coerced)
    judge_scores = [
        s
        for s in _runrecord("judge-calibration", "judge-calibration")["scores"]
        if s["metric"] == "faithfulness"
    ]
    assert judge_scores, "expected committed faithfulness scores"
    assert all(s["status"] == "scored" for s in judge_scores)


def test_gallery_runrecords_carry_subject_identity() -> None:
    """Committed gallery artifacts match the current runtime shape (F1)."""
    for example, run in (
        ("groundedness", "groundedness"),
        ("judge-calibration", "judge-calibration"),
    ):
        scores = _runrecord(example, run)["scores"]
        assert scores
        assert all("example_id" in s and "unit_id" in s for s in scores)
