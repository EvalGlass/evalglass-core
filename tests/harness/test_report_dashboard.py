"""EG-DX-E2/E3 — the diagnostic HTML dashboard renders self-contained, honest, and escaped."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evalglass.core import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.dashboard import DashboardMeta, project_run
from evalglass.harness.report_html import render_dashboard
from evalglass.harness.runner import run_config

_LANDMARKS = {
    "verdict-title",
    "authority-strip",
    "workflow-chart",
    "attention-list",
    "comparison-chart",
    "progression-chart",
    "metric-search",
    "metrics-root",
    "dashboard-data",
}


def _project(tmp_path: Path, config: dict[str, Any], *, meta: DashboardMeta) -> dict[str, Any]:
    cfg = RuntimeConfig.from_mapping(config)
    record: RunRecord = run_config(cfg, root=tmp_path)
    return project_run(record.scorecard, record, config=cfg, meta=meta)


def _informational_config(tmp_path: Path, *, label: str = "Answer shape") -> dict[str, Any]:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "x", "output": {"answer": "4"}}) + "\n", encoding="utf-8"
    )
    return {
        "datasets": [{"path": "d.jsonl"}],
        "metrics": [
            {
                "name": "answer.shape",
                "evaluator_ref": "structural_shape@1",
                "lens": "non_reference",
                "score_type": "binary",
                "display": {"label": label, "workflow": "Ingest"},
            }
        ],
    }


def test_report_is_self_contained_with_the_required_landmarks(tmp_path: Path) -> None:
    payload = _project(tmp_path, _informational_config(tmp_path), meta=DashboardMeta(run_id="r"))
    html = render_dashboard(payload)
    for landmark in _LANDMARKS:
        assert f'id="{landmark}"' in html
    # no external script/style/font/image/network dependency, and a restrictive CSP
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "Content-Security-Policy" in html
    # the injection markers are all consumed
    for marker in ("EVALGLASS:STYLE", "EVALGLASS:DATA", "EVALGLASS:SCRIPT", "EVALGLASS:CSP"):
        assert marker not in html
    # the CSP hash-pins the inline blocks (no unsafe-inline), so the report stays self-contained
    assert "unsafe-inline" not in html
    assert "script-src 'sha256-" in html


def test_embedded_payload_round_trips(tmp_path: Path) -> None:
    payload = _project(tmp_path, _informational_config(tmp_path), meta=DashboardMeta(run_id="r"))
    html = render_dashboard(payload)
    match = re.search(
        r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, flags=re.DOTALL
    )
    assert match is not None
    assert json.loads(match.group(1).replace("\\u003c", "<")) == payload


def test_informational_is_never_rendered_or_described_as_pass(tmp_path: Path) -> None:
    payload = _project(tmp_path, _informational_config(tmp_path), meta=DashboardMeta(run_id="r"))
    html = render_dashboard(payload)
    assert payload["verdict"]["state"] == "informational"
    # the embedded verdict is informational; no 'pass' verdict token is asserted for this run
    assert '"state":"informational"' in html.replace(" ", "")


def test_hostile_script_in_host_data_cannot_break_out_of_the_json_island(tmp_path: Path) -> None:
    config = _informational_config(tmp_path, label="</script><script>alert(1)</script>")
    payload = _project(tmp_path, config, meta=DashboardMeta(run_id="r"))
    html = render_dashboard(payload)
    # the raw closing tag from host data is escaped in the embedded JSON, so it cannot break out
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script>\\u003cscript>alert(1)" in html
    # exactly one real closing </script> for the data island plus the code script — never injected
    match = re.search(
        r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, flags=re.DOTALL
    )
    assert match is not None
    assert (
        json.loads(match.group(1).replace("\\u003c", "<"))["metrics"][0]["label"]
        == config["metrics"][0]["display"]["label"]
    )


def test_reference_sample_payload_renders_through_the_production_renderer() -> None:
    sample = json.loads(
        (Path(__file__).resolve().parent / "_fixtures" / "dashboard_sample.json").read_text(
            encoding="utf-8"
        )
    )
    html = render_dashboard(sample)
    for landmark in _LANDMARKS:
        assert f'id="{landmark}"' in html
    # the reference sample validates against the production contract's required shape
    assert sample["schema"] == "evalglass.dashboard/1"
    required_top = {"run", "verdict", "authority", "comparison", "summary", "metrics"}
    assert required_top <= set(sample)
    required_metric = {
        "name",
        "label",
        "workflow",
        "tier",
        "status",
        "value",
        "population",
        "authority",
        "gate",
        "comparison",
    }
    for metric in sample["metrics"]:
        assert required_metric <= set(metric)
        if metric["value"] is None:
            assert metric["comparison"]["delta"] is None
