"""CLI persistence of the lane side channel (EG-H0-6; ADR 0031).

The persisted ``runrecord.json`` carries the canonical ``lane_results`` when lanes ran; an optional
``lane_results.json`` sidecar is **byte-derived** from it. The ``scorecard.json``, Markdown report,
terminal/CI output, and exit code stay derived only from the Scorecard — a lane never moves them.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.harness.cli import main

_CONFIG_WITH_LANE = """
datasets:
  - path: d.jsonl
    status: validated
    data_policy: permitted
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl
lanes:
  - name: score-sink-export
    enabled: true
    options:
      export_dir: exports
"""

_CONFIG_NO_LANE = """
datasets:
  - path: d.jsonl
    status: validated
    data_policy: permitted
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl
"""


def _setup(tmp_path: Path, config_body: str) -> Path:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(config_body, encoding="utf-8")
    return cfg


def _run_dir(out_base: Path) -> Path:
    return next(out_base.glob("**/runrecord.json")).parent


def test_runrecord_persists_lane_results_and_sidecar_is_byte_derived(tmp_path: Path) -> None:
    cfg = _setup(tmp_path, _CONFIG_WITH_LANE)
    assert main(["run", "--config", str(cfg), "--out", "out"]) == 0
    run_dir = _run_dir(tmp_path / "out")

    runrecord = json.loads((run_dir / "runrecord.json").read_text(encoding="utf-8"))
    assert runrecord["lane_results"][0]["lane"] == "score-sink-export"
    assert runrecord["lane_results"][0]["status"] == "ran"

    sidecar = run_dir / "lane_results.json"
    assert sidecar.is_file()
    # Byte-derived: the sidecar is exactly the runrecord's lane_results.
    assert json.loads(sidecar.read_text(encoding="utf-8")) == runrecord["lane_results"]

    # The verdict-bearing summary stays lane-free, and the report renders from it.
    scorecard = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert "lane_results" not in scorecard
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "informational" in report.lower()


def test_no_lane_run_writes_no_sidecar_and_no_lane_results_key(tmp_path: Path) -> None:
    cfg = _setup(tmp_path, _CONFIG_NO_LANE)
    assert main(["run", "--config", str(cfg), "--out", "out"]) == 0
    run_dir = _run_dir(tmp_path / "out")

    runrecord = json.loads((run_dir / "runrecord.json").read_text(encoding="utf-8"))
    assert "lane_results" not in runrecord  # empty side channel is omitted
    assert not (run_dir / "lane_results.json").exists()  # no sidecar without lane results
