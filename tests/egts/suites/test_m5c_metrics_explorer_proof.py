"""EGTS-M5C-8 — metrics-explorer proof (Report Proof, Trust Proof).

Proves the real product metrics explorer (EG-H4) over real-run artifacts:

* ``m5c.metrics_explorer.typed_only`` — the view derives from the typed ``runrecord.json`` only and
  echoes the Scorecard verdict + each metric's resolved authority verbatim; it recomputes nothing
  and imports no Verdict Engine / authority resolver / aggregator;
* ``m5c.metrics_explorer.group_by_identity`` — score rows group by explicit ``(example_id,
  unit_id)`` and the grouping is invariant to score order (an order-based negative control is
  detectably wrong);
* ``m5c.metrics_explorer.old_artifact_refuses_guess`` — a score without explicit identity is
  diagnosed and excluded, never guessed by list position; there is no per-source-function view.

Scenario ids map to EG-M5C-8; EG-M5C-7 (per-source-function) stays not_started (ADR 0032).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from evalglass.core.results import RunRecord
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.harness.explorer import ExplorerView, build_view, explore
from tests.scorecard_factory import informational_record


def _score(metric: str, example_id: str | None, *, unit_id: str | None = None) -> Score:
    return Score(
        metric=metric,
        value=1.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=f"{metric}@1",
        example_id=example_id,
        unit_id=unit_id if unit_id is not None else example_id,
    )


def _with_scores(tmp_path: Path, scores: list[Score]) -> RunRecord:
    return dataclasses.replace(informational_record(tmp_path), scores=scores)


def test_m5c_metrics_explorer_typed_only(tmp_path: Path) -> None:
    """m5c.metrics_explorer.typed_only — the view reads the typed artifact and echoes the verdict +
    resolved authority verbatim, recomputing nothing."""
    record = informational_record(tmp_path)
    path = tmp_path / "runrecord.json"
    path.write_text(json.dumps(record.to_dict()), encoding="utf-8")
    baseline = record.scorecard.baseline_state
    assert baseline is not None
    view = explore(path)
    assert view.verdict == record.scorecard.verdict.verdict.value
    assert view.baseline_state == baseline.value
    [row] = view.subjects[0].rows
    assert row.authority == record.scorecard.authority[row.metric].to_dict()

    from evalglass.harness import explorer as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("core.verdict", "resolve_authority", "core.authority", "core.aggregation")
    assert [t for t in banned if t in src] == []


def test_m5c_metrics_explorer_group_by_identity(tmp_path: Path) -> None:
    """m5c.metrics_explorer.group_by_identity — groups by identity, invariant to order."""
    scores = [_score("exact_match", "ex1"), _score("length", "ex1"), _score("toxicity", "ex2")]

    def as_map(view: ExplorerView) -> dict[tuple[str, str | None], list[str]]:
        return {(s.example_id, s.unit_id): sorted(r.metric for r in s.rows) for s in view.subjects}

    forward = as_map(build_view(_with_scores(tmp_path, scores)))
    reverse = as_map(build_view(_with_scores(tmp_path, list(reversed(scores)))))
    assert forward == {("ex1", "ex1"): ["exact_match", "length"], ("ex2", "ex2"): ["toxicity"]}
    assert reverse == forward


def test_m5c_metrics_explorer_unit_id_participates_in_identity(tmp_path: Path) -> None:
    """The grouping key is the FULL ``(example_id, unit_id)`` — two units under the SAME example are
    distinct subjects, so an explorer that grouped by example_id alone would wrongly merge them."""
    scores = [_score("m1", "ex1", unit_id="u1"), _score("m2", "ex1", unit_id="u2")]
    view = build_view(_with_scores(tmp_path, scores))
    assert sorted((s.example_id, s.unit_id) for s in view.subjects) == [
        ("ex1", "u1"),
        ("ex1", "u2"),
    ]


def test_m5c_metrics_explorer_old_artifact_refuses_guess(tmp_path: Path) -> None:
    """m5c.metrics_explorer.old_artifact_refuses_guess — a score without identity is diagnosed and
    excluded, never grouped by list position."""
    view = build_view(_with_scores(tmp_path, [_score("orphan", None)]))
    assert view.subjects == []
    assert view.diagnostics
    assert "example_id" in view.diagnostics[0]


def test_negctl_order_based_grouping_is_detectably_wrong(tmp_path: Path) -> None:
    """Negative control: a position-chunking grouping changes under reordering — so it cannot be a
    correct subject identity, proving the identity grouping above is not tautological."""
    scores = [_score("a", "ex1"), _score("b", "ex2"), _score("c", "ex1")]

    def by_order(s: list[Score]) -> dict[int, list[str]]:
        return {i // 2: [sc.metric for sc in s[i // 2 * 2 : i // 2 * 2 + 2]] for i in range(len(s))}

    assert by_order(scores) != by_order(list(reversed(scores)))
