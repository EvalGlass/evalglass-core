"""EG-DX-E1 — the dashboard projection copies typed facts and infers nothing (honest)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalglass.core import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.dashboard import (
    DASHBOARD_SCHEMA,
    NEUTRAL_WORKFLOW,
    DashboardMeta,
    project_run,
)
from evalglass.harness.runner import run_config

_DASHBOARD_SRC = (
    Path(__file__).resolve().parents[2] / "src" / "evalglass" / "harness" / "dashboard.py"
).read_text(encoding="utf-8")


def _write_dataset(tmp_path: Path, rows: list[dict[str, Any]]) -> None:
    (tmp_path / "d.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _run(tmp_path: Path, config: dict[str, Any]) -> tuple[RunRecord, RuntimeConfig]:
    cfg = RuntimeConfig.from_mapping(config)
    return run_config(cfg, root=tmp_path), cfg


def _informational(tmp_path: Path, *, display: dict[str, Any] | None = None) -> dict[str, Any]:
    _write_dataset(tmp_path, [{"input": "2+2", "output": {"answer": "4"}}])
    metric: dict[str, Any] = {
        "name": "answer.shape",
        "evaluator_ref": "structural_shape@1",
        "lens": "non_reference",
        "score_type": "binary",
    }
    if display is not None:
        metric["display"] = display
    return {"datasets": [{"path": "d.jsonl"}], "metrics": [metric]}


def _gating(tmp_path: Path, *, output: str) -> dict[str, Any]:
    _write_dataset(tmp_path, [{"input": "2+2", "output": output, "reference": "4"}])
    return {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "metrics": [
            {
                "name": "exact_match",
                "evaluator_ref": "exact_match@1",
                "lens": "reference",
                "score_type": "binary",
                "dataset": "d.jsonl",
                "threshold": 1.0,
                "metric_status": "gating",
                "threshold_approval": "approved",
            }
        ],
    }


def _project(tmp_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    record, cfg = _run(tmp_path, config)
    return project_run(
        record.scorecard, record, config=cfg, meta=DashboardMeta(run_id=record.run_id)
    )


def test_projection_has_the_versioned_schema_and_required_sections(tmp_path: Path) -> None:
    payload = _project(tmp_path, _informational(tmp_path))
    assert payload["schema"] == DASHBOARD_SCHEMA
    assert {"run", "verdict", "authority", "comparison", "summary", "metrics"} <= set(payload)
    assert payload["verdict"]["state"] == "informational"
    assert payload["verdict"]["ci_should_fail"] is False
    assert payload["authority"]["active_gates"] == 0
    json.dumps(payload)  # JSON-serializable


def test_non_scored_metric_is_absent_never_zero(tmp_path: Path) -> None:
    # A field_presence over an output with no fields is non-evaluable -> value is null, not 0.0.
    _write_dataset(tmp_path, [{"input": "x", "output": "not a mapping"}])
    config = {
        "datasets": [{"path": "d.jsonl"}],
        "metrics": [
            {
                "name": "fields",
                "evaluator_ref": "field_presence@1",
                "lens": "non_reference",
                "score_type": "continuous",
                "score_range": [0, 1],
                "params": {"required_fields": ["answer"]},
            }
        ],
    }
    payload = _project(tmp_path, config)
    metric = payload["metrics"][0]
    assert metric["value"] is None
    assert metric["status"] != "scored"
    assert metric["comparison"]["delta"] is None


def test_display_metadata_is_used_and_absent_falls_back_neutrally(tmp_path: Path) -> None:
    payload = _project(
        tmp_path,
        _informational(
            tmp_path,
            display={"label": "Answer shape", "workflow": "Ingest", "description": "well-formed?"},
        ),
    )
    metric = payload["metrics"][0]
    assert metric["label"] == "Answer shape"
    assert metric["workflow"] == "Ingest"
    assert metric["description"] == "well-formed?"

    # No display metadata -> deterministic neutral fallbacks (label = name, neutral workflow group).
    plain = _project(tmp_path, _informational(tmp_path))["metrics"][0]
    assert plain["label"] == "answer.shape"
    assert plain["workflow"] == NEUTRAL_WORKFLOW


def test_tier_derives_from_typed_lens_not_the_metric_name(tmp_path: Path) -> None:
    # 'answer.shape' has a dotted name but tier must come from the typed lens, not a name split.
    payload = _project(tmp_path, _informational(tmp_path))
    assert payload["metrics"][0]["tier"] == "runtime"  # non_reference -> runtime
    # a reference metric -> 'reference' tier from the typed lens
    ref = _project(tmp_path, _gating(tmp_path, output="4"))["metrics"][0]
    assert ref["tier"] == "reference"


def test_verdict_gate_and_authority_are_copied_from_typed_contracts(tmp_path: Path) -> None:
    passing = _project(tmp_path, _gating(tmp_path, output="4"))
    assert passing["verdict"]["state"] == "pass"
    assert passing["metrics"][0]["gate"]["state"] == "pass"
    assert passing["metrics"][0]["authority"]["can_gate"] is True

    failing = _project(tmp_path, _gating(tmp_path, output="wrong"))
    assert failing["verdict"]["state"] == "fail"
    assert failing["verdict"]["ci_should_fail"] is True
    assert failing["metrics"][0]["gate"]["state"] == "fail"


def test_numeric_delta_only_when_comparable(tmp_path: Path) -> None:
    payload = _project(tmp_path, _informational(tmp_path))
    # No baseline was requested -> the comparison is typed, with no numeric delta and no claim.
    assert payload["comparison"]["state"] == "comparison_not_requested"
    metric = payload["metrics"][0]
    assert metric["comparison"]["delta"] is None
    assert metric["comparison"]["direction_adjusted_delta"] is None
    assert metric["comparison"]["outcome"] == "not_evaluable"


def test_attention_rule_is_presentation_only_and_never_changes_the_verdict(tmp_path: Path) -> None:
    # An attention rule that fires does not change the informational verdict or CI.
    payload = _project(
        tmp_path,
        _informational(tmp_path, display={"attention": {"below": 2.0, "note": "watch this"}}),
    )
    assert payload["verdict"]["state"] == "informational"
    assert payload["verdict"]["ci_should_fail"] is False
    metric = payload["metrics"][0]
    assert metric.get("attention", {}).get("flagged") is True
    assert metric.get("attention", {}).get("kind") == "host_rule"


def test_projection_imports_no_verdict_engine_or_authority_resolver() -> None:
    # Negative control (E1): the projection copies typed fields; it must not import the deciders.
    assert "decide_verdict" not in _DASHBOARD_SRC
    assert "resolve_authority" not in _DASHBOARD_SRC
    assert "run_evaluation" not in _DASHBOARD_SRC
    assert "from evalglass.core.verdict import" not in _DASHBOARD_SRC
    assert "from evalglass.core.authority import" not in _DASHBOARD_SRC


def test_projection_does_no_aggregate_subtraction() -> None:
    # Negative control (E1): a delta is only ever the typed D4 comparison, never current-previous.
    # No deprecated previous-value input, and no code line subtracts one value from another.
    assert "previous_values" not in _DASHBOARD_SRC
    code_lines = [
        line
        for line in _DASHBOARD_SRC.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "*", '"""', ":"))
    ]
    assert not any(" - " in line and "delta" in line.lower() for line in code_lines)
    assert "direction_adjusted_delta" in _DASHBOARD_SRC  # it reads the typed delta instead


def test_projection_tolerates_and_carries_declared_links_and_composite(tmp_path: Path) -> None:
    config = _informational(tmp_path, display={"docs_url": "docs/x.md", "owner": "team-a"})
    config["dashboard"] = {"composite": {"name": "overall", "version": "1", "weights": {}}}
    payload = _project(tmp_path, config)
    assert payload["metrics"][0]["links"] == {"docs_url": "docs/x.md", "owner": "team-a"}
    assert payload["composite"]["name"] == "overall"


def test_hostile_unicode_and_long_labels_survive_projection(tmp_path: Path) -> None:
    nasty = "<script>alert(1)</script> — Ω " + "x" * 300
    payload = _project(tmp_path, _informational(tmp_path, display={"label": nasty}))
    assert payload["metrics"][0]["label"] == nasty  # carried verbatim; escaping happens at render
