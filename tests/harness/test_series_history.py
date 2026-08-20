"""EG-DX-E4 — immutable run series: append-only history, verified-previous, and repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalglass.core import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config
from evalglass.harness.series import (
    entry_for,
    previous_verified_run,
    read_index,
    record_run,
    repair_index,
    run_key_for,
)


def _record(tmp_path: Path, output: str) -> RunRecord:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": output, "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "run": {"id": "suite"},
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [
                {
                    "name": "exact_match",
                    "evaluator_ref": "exact_match@1",
                    "lens": "reference",
                    "score_type": "binary",
                    "dataset": "d.jsonl",
                }
            ],
        }
    )
    return run_config(cfg, root=tmp_path)


def test_record_run_writes_an_immutable_snapshot_and_a_verified_index_entry(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    record = _record(tmp_path, "4")
    history = record_run(base, record, series_id="suite", generated_at="2026-01-01T00:00:00+00:00")
    key = run_key_for(record)
    snap = base / ".series" / "runs" / key
    assert (snap / "run.complete").is_file()  # completion marker written last
    entries = read_index(base)
    assert [e.run_key for e in entries] == [key]
    assert entries[0].series_id == "suite"
    assert history == [
        {
            "run_id": "suite",
            "examples": 1,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "evaluability": 1.0,
        }
    ]


def test_identical_rerun_is_idempotent_and_never_duplicates_history(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    record = _record(tmp_path, "4")
    record_run(base, record, series_id="suite")
    record_run(base, record, series_id="suite")  # identical digest -> no second entry
    assert len(read_index(base)) == 1


def test_a_distinct_result_appends_a_new_immutable_entry(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    good = _record(tmp_path, "4")
    record_run(base, good, series_id="suite", generated_at="2026-01-01T00:00:00+00:00")
    bad = _record(tmp_path, "wrong")
    record_run(base, bad, series_id="suite", generated_at="2026-01-02T00:00:00+00:00")
    keys = [e.run_key for e in read_index(base)]
    assert keys == [run_key_for(good), run_key_for(bad)]
    assert run_key_for(good) != run_key_for(bad)


def test_previous_verified_run_selects_the_prior_verified_snapshot(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    good = _record(tmp_path, "4")
    record_run(base, good, series_id="suite")
    bad = _record(tmp_path, "wrong")
    record_run(base, bad, series_id="suite")
    prev = previous_verified_run(base, "suite", before_key=run_key_for(bad))
    assert prev is not None
    assert prev.name == run_key_for(good)
    # the first run has no previous
    assert previous_verified_run(base, "suite", before_key=run_key_for(good)) is None


def test_a_tampered_snapshot_is_never_selected_as_previous(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    good = _record(tmp_path, "4")
    record_run(base, good, series_id="suite")
    bad = _record(tmp_path, "wrong")
    record_run(base, bad, series_id="suite")
    # corrupt the prior snapshot's scorecard so its manifest digest no longer matches
    scorecard = base / ".series" / "runs" / run_key_for(good) / "scorecard.json"
    scorecard.write_text(scorecard.read_text(encoding="utf-8") + "\n// tampered", encoding="utf-8")
    assert previous_verified_run(base, "suite", before_key=run_key_for(bad)) is None


def test_repair_rebuilds_the_index_from_verified_snapshots(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    good = _record(tmp_path, "4")
    record_run(base, good, series_id="suite")
    bad = _record(tmp_path, "wrong")
    record_run(base, bad, series_id="suite")
    # delete the index entirely; repair recovers it from the immutable snapshots
    (base / ".series" / "index.jsonl").unlink()
    recovered = repair_index(base)
    assert {e.run_key for e in recovered} == {run_key_for(good), run_key_for(bad)}
    # a corrupt snapshot is skipped, never invented
    bad_snap = base / ".series" / "runs" / run_key_for(bad) / "runrecord.json"
    bad_snap.write_text("{not json", encoding="utf-8")
    (base / ".series" / "index.jsonl").unlink()
    recovered2 = repair_index(base)
    assert {e.run_key for e in recovered2} == {run_key_for(good)}


def test_history_point_is_descriptive_and_carries_no_regression_language(tmp_path: Path) -> None:
    record = _record(tmp_path, "4")
    entry = entry_for(record, series_id="suite", generated_at="2026-01-01T00:00:00+00:00")
    point: dict[str, Any] = entry.history_point()
    # descriptive coverage facts only — no delta/outcome/regression fields
    assert set(point) <= {"run_id", "examples", "generated_at", "evaluability"}
    assert "delta" not in point
    assert "outcome" not in point
