"""Preflight + dry-run and plan/execution reconciliation.

Proves preflight and dry-run resolve the plan without any effect (no judge call, no replay
subprocess, no network), that text and JSON reconcile, and that a completed run persists a
reconciled plan digest + counts on the RunRecord.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalglass.harness.config import RuntimeConfig
from evalglass.harness.preflight import report_preflight
from evalglass.harness.runner import preflight, run_config


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _judge_config(tmp_path: Path, egress: str = "permitted") -> dict[str, Any]:
    _write(
        tmp_path / "d.jsonl",
        [
            {"example_id": "a", "input": "q", "output": "a", "metadata": {"wf": "keep"}},
            {"example_id": "b", "input": "q", "output": "b", "metadata": {"wf": "drop"}},
        ],
    )
    return {
        "datasets": [{"path": "d.jsonl", "status": "proposed", "data_policy": egress}],
        "judge": {"adapter": "fake", "default_value": 0.9},
        "metrics": [
            {
                "name": "faith",
                "evaluator_ref": "judge_score@1",
                "lens": "non_reference",
                "score_type": "continuous",
                "score_range": [0.0, 1.0],
                "required_evidence": ["judge"],
                "applies_to": {"wf": ["keep"]},
            }
        ],
    }


def test_preflight_reports_planned_requests_without_effect(tmp_path: Path) -> None:
    cfg = RuntimeConfig.from_mapping(_judge_config(tmp_path))
    report = report_preflight(cfg, tmp_path)
    # one judge metric selecting only "keep" → one planned judge request (not two)
    assert report.planned_judge_requests == 1
    assert report.subjects == 2
    faith = next(m for m in report.metrics if m.metric == "faith")
    assert faith.selector_matched == 1
    assert faith.eligible == 1
    assert faith.excluded == {"selector_mismatch": 1}
    assert faith.planned_judge_requests == 1


def test_preflight_makes_no_judge_call(tmp_path: Path, monkeypatch: Any) -> None:
    # Spy: patch the fake judge's judge() to explode — preflight must never invoke it.
    from evalglass.adapters import judge_fake

    def _boom(self: Any, request: Any) -> Any:
        raise AssertionError("preflight invoked the judge — it must be side-effect-free")

    monkeypatch.setattr(judge_fake.FakeJudgeModel, "judge", _boom)
    cfg = RuntimeConfig.from_mapping(_judge_config(tmp_path))
    report = report_preflight(cfg, tmp_path)  # must not raise
    assert report.planned_judge_requests == 1


def test_dry_run_preflight_makes_no_task_subprocess(tmp_path: Path) -> None:
    # An output-less subject would trigger replay on a real run; the dry-run preflight must not.
    _write(tmp_path / "d.jsonl", [{"example_id": "a", "input": "q"}])
    (tmp_path / "task.py").write_text(
        "import sys, json\n"
        "open('CALLED', 'w').write('x')\n"
        "json.load(sys.stdin)\nprint(json.dumps({'output': {}}))\n",
        encoding="utf-8",
    )
    import sys

    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "proposed", "data_policy": "permitted"}],
            "task": {"argv": [sys.executable, "task.py"]},
            "metrics": [
                {
                    "name": "shape",
                    "evaluator_ref": "structural_shape@1",
                    "lens": "non_reference",
                    "score_type": "binary",
                }
            ],
        }
    )
    pf = preflight(cfg, tmp_path, run_lanes=False)
    assert len(pf.plan.replay_effects()) == 1  # replay is PLANNED
    assert not (tmp_path / "CALLED").exists()  # but never EXECUTED in preflight


def test_preflight_text_and_json_reconcile(tmp_path: Path) -> None:
    cfg = RuntimeConfig.from_mapping(_judge_config(tmp_path))
    report = report_preflight(cfg, tmp_path)
    payload = report.to_dict()
    assert payload["schema"] == "evalglass.preflight/1"
    assert payload["planned_effects"]["judge_requests"] == report.planned_judge_requests
    # the text render mentions the same planned counts as the JSON projection
    text = report.render_text()
    assert f"judge={report.planned_judge_requests}" in text
    assert payload["plan_fingerprint"] in text


def test_forbidden_egress_preflight_shows_denied_request(tmp_path: Path) -> None:
    cfg = RuntimeConfig.from_mapping(_judge_config(tmp_path, egress="forbidden"))
    report_preflight(cfg, tmp_path)  # preflight must not crash on a forbidden-egress source
    # the judge effect is still planned (visible), but its policy decision is denied
    plan = preflight(cfg, tmp_path, run_lanes=False).plan
    assert [e.policy_decision.value for e in plan.judge_effects()] == ["denied"]


def test_completed_run_reconciles_plan(tmp_path: Path) -> None:
    cfg = RuntimeConfig.from_mapping(_judge_config(tmp_path))
    record = run_config(cfg, tmp_path)
    assert record.plan is not None
    assert record.plan["planned"] == record.plan["handled"]
    assert record.plan["deviated"] == 0
    # the persisted digest equals a fresh preflight's fingerprint (plan/run reconcile)
    assert record.plan["fingerprint"] == preflight(cfg, tmp_path, run_lanes=True).plan.fingerprint()
