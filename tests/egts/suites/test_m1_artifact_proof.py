"""EGTS-M1 artifact, report, and open-convention proof (EGTS-M1-4 / -6).

Drives the real CLI end-to-end in an isolated workspace, then asserts the *typed* artifacts
first (``runrecord.json`` / ``scorecard.json`` round-trip through the core contracts) and the
report second (a rendering that cannot overclaim). Also proves the open-convention adapter
maps OTel/OpenInference fixtures and surfaces a mapping diagnostic when a required field is
missing — with no tracing-backend SDK on the required path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evalglass.core import RunRecord, Scorecard
from evalglass.harness.cli import main
from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config
from tests.egts.checkers import CheckerError, check_report_no_overclaim
from tests.egts.workspace import RuntimeWorkspace, make_workspace

_INFO_CONFIG = """
run:
  id: run-art
datasets:
  - path: datasets/d.jsonl
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: datasets/d.jsonl
output:
  dir: reports
"""


def _ws(tmp_path: Path) -> RuntimeWorkspace:
    return make_workspace(
        tmp_path,
        "fx-art",
        config=_INFO_CONFIG,
        datasets={"d.jsonl": json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"},
    )


def test_persisted_artifacts_round_trip_through_contracts(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    assert main(["run", "--config", str(ws.config_path)]) == 0
    run_dir = ws.reports_dir / "run-art"
    runrecord = RunRecord.from_dict(json.loads((run_dir / "runrecord.json").read_text("utf-8")))
    scorecard = Scorecard.from_dict(json.loads((run_dir / "scorecard.json").read_text("utf-8")))
    # the typed artifacts are primary and internally consistent
    assert runrecord.scorecard == scorecard
    assert runrecord.run_id == "run-art"


def test_report_renders_without_overclaim(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    main(["run", "--config", str(ws.config_path)])
    run_dir = ws.reports_dir / "run-art"
    scorecard = Scorecard.from_dict(json.loads((run_dir / "scorecard.json").read_text("utf-8")))
    report = (run_dir / "report.md").read_text("utf-8")
    check_report_no_overclaim(report, scorecard)


def test_report_overclaim_negative_control(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    main(["run", "--config", str(ws.config_path)])
    run_dir = ws.reports_dir / "run-art"
    scorecard = Scorecard.from_dict(json.loads((run_dir / "scorecard.json").read_text("utf-8")))
    report = (run_dir / "report.md").read_text("utf-8")
    # a tampered report that claims a pass while the Scorecard is informational must fail
    tampered = report.replace("**Verdict:** informational", "**Verdict:** pass")
    with pytest.raises(CheckerError):
        check_report_no_overclaim(tampered, scorecard)


# --- open-convention mapping (EGTS-M1-4) ------------------------------------


def _open_convention_ws(
    tmp_path: Path, fixture_id: str, span: dict[str, object], *, fmt: str = "openinference"
) -> RuntimeWorkspace:
    config = (
        f"traces:\n  - path: traces/t.jsonl\n    format: {fmt}\n"
        "    data_policy: permitted\n"
        "metrics:\n  - name: structural_shape\n    evaluator_ref: structural_shape@1\n"
        "    lens: non_reference\n    score_type: binary\n"
    )
    return make_workspace(
        tmp_path, fixture_id, config=config, traces={"t.jsonl": json.dumps(span) + "\n"}
    )


def test_openinference_span_maps_and_scores(tmp_path: Path) -> None:
    span: dict[str, object] = {
        "context": {"trace_id": "t1"},
        "attributes": {"llm.output_messages": [{"message.content": "hi"}]},
    }
    ws = _open_convention_ws(tmp_path, "fx-oinf-ok", span, fmt="openinference")
    record = run_config(load_config(ws.config_path), root=ws.root)
    assert record.scores  # the span mapped to an Example and was scored
    assert not record.scorecard.diagnostics


def test_opentelemetry_span_maps_and_scores(tmp_path: Path) -> None:
    # Exercise the OTel branch (gen_ai.* attributes), not only OpenInference.
    span: dict[str, object] = {
        "span_id": "s1",
        "attributes": {"gen_ai.completion": "hi", "gen_ai.request.model": "m-1"},
    }
    ws = _open_convention_ws(tmp_path, "fx-otel-ok", span, fmt="opentelemetry")
    record = run_config(load_config(ws.config_path), root=ws.root)
    assert record.scores
    assert not record.scorecard.diagnostics


def test_open_convention_missing_output_surfaces_mapping_diagnostic(tmp_path: Path) -> None:
    span: dict[str, object] = {"context": {"trace_id": "t1"}, "attributes": {"input.value": "q"}}
    ws = _open_convention_ws(tmp_path, "fx-oinf-bad", span)
    record = run_config(load_config(ws.config_path), root=ws.root)
    assert "trace_mapping_incomplete" in {d.code for d in record.scorecard.diagnostics}


def test_open_convention_route_imports_no_tracing_sdk(tmp_path: Path) -> None:
    # Required tier is hermetic: assert *this run* imported no tracing backend SDK, rather than
    # that the module names are globally absent (another plugin may have loaded one).
    def _tracing_modules() -> set[str]:
        return {m for m in sys.modules if m.split(".", 1)[0] in {"opentelemetry", "openinference"}}

    before = _tracing_modules()
    span: dict[str, object] = {"trace_id": "t1", "attributes": {"output.value": "a"}}
    ws = _open_convention_ws(tmp_path, "fx-otel-hermetic", span)
    run_config(load_config(ws.config_path), root=ws.root)
    assert _tracing_modules() == before  # the run imported no new tracing SDK
