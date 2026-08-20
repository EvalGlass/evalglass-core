"""Real metrics-explorer reader + subject grouping (EG-H4-1, EG-H4-3).

The explorer is a read-only VIEW over typed product artifacts (``runrecord.json``). It is NOT a lane
and NOT a meaning engine: it reads typed fields through the contract parsers, groups score rows by
explicit subject identity ``(example_id, unit_id)``, echoes the Scorecard verdict verbatim, and
recomputes nothing. A non-scored value shows as ``None`` / ``-``, never ``0.0``; a score without
explicit identity is diagnosed, never guessed.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from evalglass.core import Diagnostic, Severity
from evalglass.core.results import RunRecord
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.harness.explorer import (
    ExplorerError,
    SubjectGroup,
    build_view,
    explore,
    read_run_record,
)
from tests.scorecard_factory import informational_record


def _write_record(tmp_path: Path) -> Path:
    record = informational_record(tmp_path)
    path = tmp_path / "runrecord.json"
    path.write_text(json.dumps(record.to_dict(), sort_keys=True), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# EG-H4-1 — typed artifact reader                                             #
# --------------------------------------------------------------------------- #
def test_explore_reads_typed_artifact_and_echoes_verdict(tmp_path: Path) -> None:
    record = informational_record(tmp_path)
    path = _write_record(tmp_path)
    view = explore(path)
    # The verdict is echoed verbatim from the Scorecard — never recomputed.
    assert view.verdict == record.scorecard.verdict.verdict.value
    assert view.ci_should_fail == record.scorecard.verdict.ci_should_fail
    assert view.run_id == record.run_id
    assert view.subjects, "the real run produced at least one grouped subject"


def test_explore_reader_imports_no_meaning_engine_or_network() -> None:
    from evalglass.harness import explorer as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    banned = (
        "core.verdict",
        "resolve_authority",
        "core.authority",
        "core.aggregation",
        "import socket",
        "urllib",
        "subprocess",
    )
    assert [t for t in banned if t in src] == []


def test_old_artifact_without_lane_results_parses(tmp_path: Path) -> None:
    record = informational_record(tmp_path)
    data = record.to_dict()
    data.pop("lane_results", None)  # an old artifact predating the seam
    path = tmp_path / "old.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_run_record(path).lane_results == []


@pytest.mark.parametrize(
    "body",
    [
        "{not json",  # invalid JSON
        '{"run_id": "r"}',  # missing required scorecard/scores
        '{"run_id": "", "scorecard": {}, "scores": []}',  # blank run_id
    ],
)
def test_malformed_artifact_fails_closed(tmp_path: Path, body: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ExplorerError):
        read_run_record(path)


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ExplorerError):
        read_run_record(tmp_path / "does-not-exist.json")


# --------------------------------------------------------------------------- #
# EG-H4-3 — grouping by explicit subject identity                            #
# --------------------------------------------------------------------------- #
def _record_with_scores(tmp_path: Path, scores: list[Score]) -> RunRecord:
    return dataclasses.replace(informational_record(tmp_path), scores=scores)


def _score(metric: str, example_id: str | None, *, value: float | None = 1.0) -> Score:
    status = ScoreStatus.SCORED if value is not None else ScoreStatus.BLOCKED
    validity = Validity.VALID if value is not None else Validity.NOT_MEASURED
    return Score(
        metric=metric,
        value=value,
        status=status,
        validity=validity,
        evaluator_version=f"{metric}@1",
        example_id=example_id,
        unit_id=example_id,
    )


def test_groups_by_explicit_identity_order_invariant(tmp_path: Path) -> None:
    scores = [_score("exact_match", "ex1"), _score("length", "ex1"), _score("toxicity", "ex2")]
    forward = build_view(_record_with_scores(tmp_path, scores))
    reverse = build_view(_record_with_scores(tmp_path, list(reversed(scores))))
    subjects = {
        (s.example_id, s.unit_id): sorted(r.metric for r in s.rows) for s in forward.subjects
    }
    assert subjects == {("ex1", "ex1"): ["exact_match", "length"], ("ex2", "ex2"): ["toxicity"]}
    # Grouping is by identity, not list order — reordering the scores yields the same subjects.
    reverse_subjects = {
        (s.example_id, s.unit_id): sorted(r.metric for r in s.rows) for s in reverse.subjects
    }
    assert reverse_subjects == subjects


def test_non_scored_value_is_null_never_zero(tmp_path: Path) -> None:
    """A blocked/non-scored row shows value None and displays as '-', never 0.0."""
    view = build_view(_record_with_scores(tmp_path, [_score("blocked_metric", "ex1", value=None)]))
    [row] = view.subjects[0].rows
    assert row.value is None
    assert row.display_value == "-"
    assert row.status == "blocked"


def test_scored_but_invalid_row_preserves_status_validity_and_diagnostics(tmp_path: Path) -> None:
    """A scored-but-invalid row honestly carries status='scored' AND validity='invalid' (with its
    diagnostic), so a null value is explained — never a silent scored row with a missing number."""
    invalid = Score(
        metric="judge",
        value=0.3,
        status=ScoreStatus.SCORED,
        validity=Validity.INVALID,
        evaluator_version="judge@1",
        diagnostics=[Diagnostic(code="judge_uncalibrated", severity=Severity.WARNING, message="x")],
        example_id="ex1",
        unit_id="ex1",
    )
    [row] = build_view(_record_with_scores(tmp_path, [invalid])).subjects[0].rows
    assert row.status == "scored"
    assert row.validity == "invalid"
    assert row.value is None  # an invalid measurement is not a real value
    assert row.diagnostics == ["judge_uncalibrated"]
    assert row.to_dict()["validity"] == "invalid"


def test_missing_identity_is_diagnosed_not_guessed(tmp_path: Path) -> None:
    """A score without example_id is diagnosed and excluded from subjects — identity is never
    guessed by list position."""
    view = build_view(_record_with_scores(tmp_path, [_score("orphan", None)]))
    assert view.subjects == []
    assert view.diagnostics
    assert "example_id" in view.diagnostics[0]


def test_view_carries_authority_and_baseline_from_the_scorecard(tmp_path: Path) -> None:
    """The view surfaces the metric's resolved authority and the run's baseline state, read verbatim
    from the Scorecard — so a value is never shown without whether it can be trusted."""
    record = informational_record(tmp_path)
    baseline = record.scorecard.baseline_state
    assert baseline is not None
    view = build_view(record)
    assert view.baseline_state == baseline.value
    [row] = view.subjects[0].rows
    assert row.authority == record.scorecard.authority[row.metric].to_dict()
    assert row.authority is not None
    assert row.authority["can_gate"] is False


def test_view_makes_no_per_source_function_claim() -> None:
    """The view groups by subject identity only — there is no per-source-function attribution."""
    fields = {f.name for f in dataclasses.fields(SubjectGroup)}
    assert fields == {"example_id", "unit_id", "rows"}
    assert not any("source" in f or "function" in f for f in fields)
