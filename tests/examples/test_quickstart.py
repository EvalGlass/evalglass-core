"""The shipped quickstart sample runs honestly (EG-M1-6).

The sample must exercise both routes locally with no network, produce real scores, and stay
**informational** — a sample can never imply validated domain truth. We drive the real
config/runner against the shipped assets and (separately) the CLI against a temp copy so the
end-to-end path including persistence is covered without writing into the source tree.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evalglass.core import MetricStatus, Verdict
from evalglass.harness.cli import main
from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config

_QUICKSTART = Path(__file__).resolve().parents[2] / "examples" / "quickstart" / "evals"


def test_quickstart_assets_exist() -> None:
    assert (_QUICKSTART / "evalglass.yaml").is_file()
    assert (_QUICKSTART / "datasets" / "arithmetic.jsonl").is_file()
    assert (_QUICKSTART / "traces" / "sample.jsonl").is_file()
    assert (_QUICKSTART / "evaluators" / "answer_nonempty.py").is_file()


def test_sample_metrics_are_informational() -> None:
    cfg = load_config(_QUICKSTART / "evalglass.yaml")
    # No sample metric carries gating authority, and none proposes an approved threshold.
    assert cfg.metrics
    assert all(m.metric_status is MetricStatus.INFORMATIONAL for m in cfg.metrics)
    assert all(m.threshold is None for m in cfg.metrics)


def test_quickstart_runs_informational_over_both_routes() -> None:
    cfg = load_config(_QUICKSTART / "evalglass.yaml")
    record = run_config(cfg, root=_QUICKSTART)
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
    assert record.scorecard.verdict.ci_should_fail is False
    # dataset (3) + trace (2) examples scored by every metric → real measurements exist
    assert record.scores
    scored_metrics = {s.metric for s in record.scores}
    assert {
        "exact_match",
        "structural_shape",
        "field_presence",
        "answer_nonempty",
    } <= scored_metrics


def test_quickstart_cli_end_to_end_in_temp_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evals = tmp_path / "evals"
    shutil.copytree(_QUICKSTART, evals)
    code = main(["run", "--config", str(evals / "evalglass.yaml")])
    assert code == 0
    run_dir = evals / "reports" / "quickstart"
    assert (run_dir / "runrecord.json").is_file()
    assert (run_dir / "scorecard.json").is_file()
    assert (run_dir / "report.md").is_file()
    # the persisted scorecard is honestly informational
    scorecard = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["verdict"]["verdict"] == "informational"
    assert "informational" in capsys.readouterr().out
