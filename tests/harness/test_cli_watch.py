"""EG-P4-3 — `evalglass watch` runs one honest drift cycle; no daemon, no drift exit class."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.harness.cli import main

_CONFIG = """run:
  id: r1
datasets:
  - path: d.jsonl
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl
{baseline}output:
  dir: reports
"""


def _write(tmp_path: Path, *, output: str, baseline: str = "") -> Path:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": output, "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(_CONFIG.format(baseline=baseline), encoding="utf-8")
    return cfg


def test_watch_with_baseline_writes_drift_and_exits_per_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _write(tmp_path, output="4")
    # First run + promote a baseline.
    assert main(["run", "--config", str(cfg)]) == 0
    rr = tmp_path / "reports" / "r1" / "runrecord.json"
    baseline_path = tmp_path / "baselines" / "baseline.json"
    assert main(["baseline", "update", "--from", str(rr), "--to", str(baseline_path)]) == 0
    capsys.readouterr()
    # Point the config at the baseline and watch.
    cfg2 = _write(tmp_path, output="4", baseline="baseline:\n  path: baselines/baseline.json\n")
    rc = main(["watch", "--config", str(cfg2)])
    # Exit derives only from the run's verdict (informational → 0); drift adds no exit class.
    assert rc == 0
    assert (tmp_path / "reports" / "r1" / "drift.json").exists()
    out = capsys.readouterr().out.lower()
    assert "drift" in out or "comparable" in out
    # The baseline file is never mutated by watch.
    assert json.loads(baseline_path.read_text(encoding="utf-8"))["run_id"] == "r1"


def test_watch_without_baseline_reports_missing_not_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _write(tmp_path, output="4")  # no baseline: block
    rc = main(["watch", "--config", str(cfg)])
    assert rc == 0  # exit still verdict-derived
    out = capsys.readouterr().out.lower()
    assert "no baseline" in out or "missing_baseline" in out


def test_watch_baseline_file_never_mutated(tmp_path: Path) -> None:
    cfg = _write(tmp_path, output="4")
    main(["run", "--config", str(cfg)])
    rr = tmp_path / "reports" / "r1" / "runrecord.json"
    baseline_path = tmp_path / "baselines" / "baseline.json"
    main(["baseline", "update", "--from", str(rr), "--to", str(baseline_path)])
    before = baseline_path.read_bytes()
    cfg2 = _write(tmp_path, output="5", baseline="baseline:\n  path: baselines/baseline.json\n")
    main(["watch", "--config", str(cfg2)])  # a drifted current run
    assert baseline_path.read_bytes() == before  # watcher never promotes/updates the baseline
