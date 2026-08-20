"""Shared test helper: build a real ``Scorecard`` through the runner.

Used by the sink/export tests (product + EGTS) so the route-faithful Scorecard fixture lives in one
place rather than being duplicated per test file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalglass.core import Scorecard
from evalglass.core.results import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config


def _matching_config(tmp_path: Path) -> dict[str, Any]:
    """Write a tiny matching dataset and return the config mapping that scores it."""
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    return {
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


def informational_record(tmp_path: Path) -> RunRecord:
    """Run a tiny matching dataset through the real harness → an ``informational`` RunRecord."""
    cfg = RuntimeConfig.from_mapping(_matching_config(tmp_path))
    return run_config(cfg, root=tmp_path)


def informational_scorecard(tmp_path: Path) -> Scorecard:
    """Run a tiny matching dataset through the real harness → an ``informational`` Scorecard."""
    return informational_record(tmp_path).scorecard


def record_with_export_lane(tmp_path: Path, *, export_dir: str = "export") -> RunRecord:
    """Same run as :func:`informational_record` but with the score-sink-export lane enabled.

    The runner-attach seam (ADR 0031) runs the post-core SCORE_SINK lane and folds its
    ``LaneResult`` into ``RunRecord.lane_results`` — without touching the verdict.
    """
    cfg_data = _matching_config(tmp_path)
    cfg_data["lanes"] = [
        {"name": "score-sink-export", "enabled": True, "options": {"export_dir": export_dir}}
    ]
    cfg = RuntimeConfig.from_mapping(cfg_data)
    return run_config(cfg, root=tmp_path)
