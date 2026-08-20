"""The ``evalglass view`` read-only metrics-explorer command (EG-H4-2).

``view`` inspects a run's metrics from its typed ``runrecord.json`` artifact. It is read-only — it
writes nothing and mutates no host truth — and it is **not** a second CI gate: it echoes the stored
verdict and always exits ``0`` on a successful read (a malformed artifact is an infrastructure
error, never a quality fail).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.harness.cli import main
from tests.scorecard_factory import informational_record


def _runrecord(tmp_path: Path) -> Path:
    record = informational_record(tmp_path)
    path = tmp_path / "runrecord.json"
    path.write_text(json.dumps(record.to_dict()), encoding="utf-8")
    return path


def test_view_text_echoes_verdict_and_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["view", "--record", str(_runrecord(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "informational" in out  # the stored verdict, echoed
    assert "exact_match" in out  # the metric for the run's subject
    # The value's trust context travels with it: the metric's resolved authority + baseline state.
    assert "authority:" in out
    assert "baseline:" in out


def test_view_json_output_is_the_explorer_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["view", "--record", str(_runrecord(tmp_path)), "--format", "json"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "informational"
    assert data["baseline_state"] == "comparison_not_requested"
    assert data["subjects"], "the view lists the run's subjects"
    row = data["subjects"][0]["rows"][0]
    assert row["validity"] == "valid"
    # The metric's resolved authority accompanies the value, read verbatim from the Scorecard.
    assert row["authority"]["level"] == "informational"
    assert row["authority"]["can_gate"] is False


def test_view_malformed_artifact_is_infrastructure_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code = main(["view", "--record", str(bad)])
    err = capsys.readouterr().err
    assert code == 2  # infrastructure/setup error, never a fabricated quality fail
    assert "explorer_error" in err


def test_view_is_read_only_writes_nothing(tmp_path: Path) -> None:
    path = _runrecord(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    main(["view", "--record", str(path)])
    assert {p.name for p in tmp_path.iterdir()} == before  # the view creates no files


def test_view_exits_zero_not_the_runs_ci_exit(tmp_path: Path) -> None:
    """The view inspects; it is not a second CI gate — a successful read exits 0 regardless of the
    stored verdict's CI exit class."""
    assert main(["view", "--record", str(_runrecord(tmp_path))]) == 0
