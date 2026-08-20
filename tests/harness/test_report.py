"""Score sinks render from the Scorecard only (EG-M1-5).

The headline verdict text is derived from ``scorecard.verdict``, so a report cannot claim a
passing gate when the run is informational — the report-overclaim guard (EGTS-M1-6's negative
control proves it rigorously against a mutated artifact).
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.ports import ScoreSink
from evalglass.harness.report import MarkdownScoreSink, TerminalScoreSink
from evalglass.harness.runner import run_config


def _metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": "d.jsonl",
    }
    base.update(over)
    return base


def _record(tmp_path: Path, *, gating: bool) -> RunRecord:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    metric = (
        _metric(metric_status="gating", threshold_approval="approved", threshold=0.5)
        if gating
        else _metric()
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [metric],
        }
    )
    return run_config(cfg, root=tmp_path)


def test_markdown_reports_informational_without_claiming_pass(tmp_path: Path) -> None:
    md = MarkdownScoreSink().render(_record(tmp_path, gating=False).scorecard)
    assert "**Verdict:** informational" in md
    assert "no active gate" in md
    assert "**Verdict:** pass" not in md


def test_markdown_reports_pass_for_a_passing_gate(tmp_path: Path) -> None:
    md = MarkdownScoreSink().render(_record(tmp_path, gating=True).scorecard)
    assert "**Verdict:** pass" in md


def test_markdown_lists_metric_and_authority(tmp_path: Path) -> None:
    md = MarkdownScoreSink().render(_record(tmp_path, gating=False).scorecard)
    assert "exact_match" in md
    assert "## Metrics" in md
    assert "## Baseline" in md


def test_terminal_reflects_verdict(tmp_path: Path) -> None:
    out = TerminalScoreSink().render(_record(tmp_path, gating=False).scorecard)
    assert "verdict: informational" in out
    assert "exact_match" in out


def test_sinks_satisfy_protocol() -> None:
    assert isinstance(MarkdownScoreSink(), ScoreSink)
    assert isinstance(TerminalScoreSink(), ScoreSink)
