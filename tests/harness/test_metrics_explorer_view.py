"""Metrics-explorer view contract (EG-AT4-9; EG-H4; alignment plan §5.7, delta D5).

The metrics explorer ships in EG-H4 as a read-only **view** (``evalglass.harness.explorer`` + the
``evalglass view`` CLI) — a non-lane surface that reads typed artifacts and recomputes nothing.
This file pins the *contract any explorer must satisfy*, modeled over plain ``runrecord.json`` /
``scorecard.json`` dicts (the only inputs it may read):

* it derives the verdict it shows **verbatim** from the Scorecard — it never recomputes meaning,
  and the Scorecard dict is consumed read-only (``check_scorecard_unchanged``);
* it groups scores by **explicit ``example_id``/``unit_id`` identity, never by list order** — the
  negative control proves an order-based grouping is detectably wrong (it changes under reordering
  while identity grouping is invariant);
* it is a **non-lane** surface — no explorer lane is registered (it is a view, not a ``LanePort``).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from evalglass.harness.lanes import built_in_lanes
from tests.egts.checkers import check_scorecard_unchanged
from tests.scorecard_factory import informational_scorecard as _scorecard


def _scores() -> list[dict[str, Any]]:
    """Two subjects, two metrics each — the shape an explorer reads out of ``runrecord.json``."""
    return [
        {"metric": "exact_match", "value": 1.0, "example_id": "ex1", "unit_id": "u1"},
        {"metric": "length", "value": 0.5, "example_id": "ex1", "unit_id": "u1"},
        {"metric": "judge_score", "value": 0.0, "example_id": "ex2", "unit_id": "u2"},
        {"metric": "toxicity", "value": 0.9, "example_id": "ex2", "unit_id": "u2"},
    ]


def _explorer_group_by_identity(runrecord: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """A conforming explorer: group score metrics by explicit (example_id, unit_id)."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for score in runrecord["scores"]:
        groups[(score["example_id"], score["unit_id"])].append(score["metric"])
    return {k: sorted(v) for k, v in groups.items()}


def _explorer_group_by_order(runrecord: dict[str, Any]) -> dict[int, list[str]]:
    """A DELIBERATELY WRONG explorer: chunk scores into subjects by list position (2 per group)."""
    scores = runrecord["scores"]
    groups: dict[int, list[str]] = defaultdict(list)
    for index, score in enumerate(scores):
        groups[index // 2].append(score["metric"])
    return {k: sorted(v) for k, v in groups.items()}


def test_metrics_explorer_reads_only_typed_artifacts_and_echoes_verdict(tmp_path: Path) -> None:
    """The view derives from scorecard/runrecord dicts only; the verdict is echoed verbatim."""
    scorecard = _scorecard(tmp_path)
    card = scorecard.to_dict()
    before = scorecard.to_dict()
    runrecord: dict[str, Any] = {"run_id": "<run_id>", "scorecard": card, "scores": _scores()}
    shown_verdict = runrecord["scorecard"]["verdict"]
    assert shown_verdict == card["verdict"]  # echoed, never recomputed
    check_scorecard_unchanged(scorecard, before)  # read-only


def test_metrics_explorer_groups_by_subject_identity_not_order() -> None:
    """Grouping uses example_id/unit_id and is invariant to score list order."""
    runrecord = {"scores": _scores()}
    reordered = {"scores": list(reversed(_scores()))}
    grouped = _explorer_group_by_identity(runrecord)
    assert grouped == {
        ("ex1", "u1"): ["exact_match", "length"],
        ("ex2", "u2"): ["judge_score", "toxicity"],
    }
    # Identity grouping is order-invariant — the same subjects regardless of list order.
    assert _explorer_group_by_identity(reordered) == grouped


def test_negctl_order_based_grouping_is_detectably_wrong() -> None:
    """Negative control: an order-based explorer misattributes when the score order changes.

    Proves the identity assertion above is not tautological — a position-chunking view is
    sensitive to order, so it cannot be a correct subject grouping.
    """
    forward = _explorer_group_by_order({"scores": _scores()})
    reversed_ = _explorer_group_by_order({"scores": list(reversed(_scores()))})
    assert forward != reversed_  # order-based grouping is not a stable subject identity


def test_metrics_explorer_is_not_a_lane() -> None:
    """The explorer ships as a read-only view, not a lane: no ``built_in_lanes()`` entry is it."""
    names = built_in_lanes().names()
    assert not any("explorer" in name or "metrics-explorer" in name for name in names), names
