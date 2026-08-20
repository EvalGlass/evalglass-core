"""EGTS — F1 artifact-shape proof (EGP-F1-4).

The plugin's ``/evalglass view --by-call`` is blocked until **real product output** carries score
subject identity (plan §10 F1; ADR 0024). This is that gate: drive the real CLI over a dataset
*and* a trace scenario, read the persisted ``runrecord.json``, and prove every individual score
carries ``example_id``/``unit_id`` — so a reader can group by call by *field*, never by list order.

Negative controls prove the gate is sensitive (a regression that drops identity fails) and that the
by-call grouping is fail-closed (it refuses to guess). Old identity-less artifacts still parse, so
the additive contract is backward compatible at the artifact level.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import RunRecord
from evalglass.harness.cli import main
from tests.egts.checkers import (
    CheckerError,
    check_scores_carry_subject_identity,
    group_scores_by_subject,
)
from tests.egts.workspace import make_workspace

# One exact_match metric runs over both routes: the dataset example (reference present → scored)
# and the trace example (no reference → non_evaluable). Both scores must still carry identity.
_CONFIG = """
run:
  id: run-f1
datasets:
  - path: datasets/d.jsonl
traces:
  - path: traces/t.jsonl
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: datasets/d.jsonl
output:
  dir: reports
"""


def _runrecord(tmp_path: Path) -> dict[str, Any]:
    ws = make_workspace(
        tmp_path,
        "fx-f1",
        config=_CONFIG,
        datasets={"d.jsonl": json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"},
        traces={
            "t.jsonl": json.dumps({"trace_id": "t1", "behavior": {"input": "q", "output": "a"}})
            + "\n"
        },
    )
    assert main(["run", "--config", str(ws.config_path)]) == 0
    raw = (ws.reports_dir / "run-f1" / "runrecord.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw)
    return data


def test_real_runrecord_scores_carry_subject_identity(tmp_path: Path) -> None:
    record = _runrecord(tmp_path)
    # the gate over real product output (dataset + trace routes both represented)
    check_scores_carry_subject_identity(record)
    scores = record["scores"]
    assert len(scores) == 2, "expected one score per converged example (dataset + trace)"
    assert len({s["example_id"] for s in scores}) == 2, (
        "dataset and trace must be distinct subjects"
    )


def test_artifact_shape_gate_negative_control(tmp_path: Path) -> None:
    """If the harness regressed and stopped stamping identity, the gate must catch it."""
    record = _runrecord(tmp_path)
    record["scores"][0].pop("example_id")
    with pytest.raises(CheckerError):
        check_scores_carry_subject_identity(record)


def test_by_call_grouping_is_fail_closed(tmp_path: Path) -> None:
    record = _runrecord(tmp_path)
    grouped = group_scores_by_subject(record)
    assert len(grouped) == 2  # grouped by explicit identity
    # a score without identity must make the reader refuse, not guess by order
    record["scores"][1].pop("unit_id")
    with pytest.raises(CheckerError):
        group_scores_by_subject(record)


def test_old_runrecord_without_identity_still_parses(tmp_path: Path) -> None:
    """Backward compatible at the artifact level: an old runrecord (no identity) still loads."""
    record = _runrecord(tmp_path)
    for score in record["scores"]:
        score.pop("example_id", None)
        score.pop("unit_id", None)
    restored = RunRecord.from_dict(record)
    assert all(s.example_id is None and s.unit_id is None for s in restored.scores)
