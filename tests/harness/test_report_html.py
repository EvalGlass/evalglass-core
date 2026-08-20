"""Legacy HTML renderer (report_html_legacy) — renders honestly, shows deltas, adds no authority."""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.ports import ScoreSink
from evalglass.harness.report_html_legacy import HtmlScoreSink, ReportMeta
from evalglass.harness.runner import run_config


def _record(tmp_path: Path, *, output: str = "4") -> RunRecord:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": output, "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = RuntimeConfig.from_mapping(
        {
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


def test_html_is_self_contained_and_states_the_verdict(tmp_path: Path) -> None:
    html = HtmlScoreSink(meta=ReportMeta(run_id="r1", source="local traces")).render(
        _record(tmp_path).scorecard
    )
    assert html.startswith("<style>") or "<style>" in html[:40]
    # self-contained: no external asset references (CSP-safe, no network)
    assert "http://" not in html
    assert "https://" not in html
    assert "src=" not in html
    assert "cdn" not in html.lower()
    # the verdict word is present and comes from the Verdict Engine (informational here)
    assert "informational" in html
    assert "exact_match" in html
    # the honesty panel is always present
    assert "does not claim" in html


def test_html_renders_the_interval_band(tmp_path: Path) -> None:
    html = HtmlScoreSink().render(_record(tmp_path).scorecard)
    # the confidence interval is visualized (an SVG band with a point), not just the number
    assert 'class="band"' in html
    assert "wilson" in html.lower() or "[" in html  # interval method / bounds in the title


def test_html_shows_delta_vs_previous(tmp_path: Path) -> None:
    # a prior run scored 1.0; this run scores 0.0 -> a downward delta chip appears
    html = HtmlScoreSink(previous_values={"exact_match": 1.0}).render(
        _record(tmp_path, output="wrong").scorecard
    )
    assert "Δ vs previous run" in html
    assert "down" in html  # a regression chip class

    # no previous -> no delta section
    html_none = HtmlScoreSink().render(_record(tmp_path).scorecard)
    assert "Δ vs previous run" not in html_none


def test_html_sink_satisfies_the_score_sink_protocol() -> None:
    assert isinstance(HtmlScoreSink(), ScoreSink)
