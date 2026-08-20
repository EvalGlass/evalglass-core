"""Effects are executed from the plan, not the metric-by-example product.

Proves through the real ``run_config`` path that judge collection is plan-scoped (a selector-
mismatched subject never reaches the judge), replay runs only for planned subjects, and the run
reconciles its plan into ``RunRecord.plan`` with no deviation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _judge_metric(name: str, selector: dict[str, list[str]] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": name,
        "evaluator_ref": "judge_score@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0.0, 1.0],
        "required_evidence": ["judge"],
    }
    if selector is not None:
        spec["applies_to"] = selector
    return spec


def test_judge_collection_is_plan_scoped_not_cartesian(tmp_path: Path) -> None:
    # 3 subjects, one judge metric selecting only the two tagged "keep". Pre-plan behaviour would
    # judge all 3 (metric by example); plan-driven collection judges exactly the 2 eligible ones.
    _write(
        tmp_path / "d.jsonl",
        [
            {"example_id": "a", "input": "q", "output": "a", "metadata": {"wf": "keep"}},
            {"example_id": "b", "input": "q", "output": "b", "metadata": {"wf": "drop"}},
            {"example_id": "c", "input": "q", "output": "c", "metadata": {"wf": "keep"}},
        ],
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "proposed", "data_policy": "permitted"}],
        "judge": {"adapter": "fake", "default_value": 0.9},
        "metrics": [_judge_metric("faith", selector={"wf": ["keep"]})],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    # The judge scored exactly the two "keep" subjects — the "drop" subject never reached it.
    judged = [
        s.example_id
        for s in record.scores
        if s.metric == "faith" and s.status.value == "scored" and s.example_id is not None
    ]
    assert sorted(judged) == ["a", "c"]
    assert "b" not in judged


def test_run_record_carries_reconciled_plan(tmp_path: Path) -> None:
    _write(tmp_path / "d.jsonl", [{"example_id": "a", "input": "q", "output": "a"}])
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "proposed", "data_policy": "permitted"}],
        "judge": {"adapter": "fake", "default_value": 0.9},
        "metrics": [_judge_metric("faith")],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    plan = record.plan
    assert plan is not None
    assert plan["schema"] == "evalglass.evaluation-plan/1"
    assert plan["fingerprint"].startswith("sha256:")
    assert plan["planned"] == 1  # one judge effect for the single subject
    assert plan["handled"] == 1
    assert plan["deviated"] == 0
    assert plan["deviations"] == []


def test_forbidden_policy_subject_makes_no_judge_call_but_reconciles(tmp_path: Path) -> None:
    # A forbidden-egress dataset: the plan still plans the judge effect, but it is handled as a
    # typed MISSING (no provider call). The effect is handled → no PLANNED_NOT_EXECUTED deviation.
    _write(tmp_path / "d.jsonl", [{"example_id": "a", "input": "q", "output": "a"}])
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "proposed", "data_policy": "forbidden"}],
        "judge": {"adapter": "fake", "default_value": 0.9},
        "metrics": [_judge_metric("faith")],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    assert record.plan is not None
    assert record.plan["deviated"] == 0  # a policy-denied effect is handled, not a deviation
    # the judge produced no numeric score for the forbidden subject
    scored = [s for s in record.scores if s.metric == "faith" and s.status.value == "scored"]
    assert scored == []


def test_replay_runs_only_for_planned_subjects(tmp_path: Path) -> None:
    # Two output-less subjects; a runtime metric selects only the one tagged "keep". The plan marks
    # only that subject for replay, so the host task is invoked for it alone — the excluded subject
    # is never sent to the subprocess.
    _write(
        tmp_path / "d.jsonl",
        [
            {"example_id": "keep1", "input": "q", "metadata": {"wf": "keep"}},
            {"example_id": "drop1", "input": "q", "metadata": {"wf": "drop"}},
        ],
    )
    (tmp_path / "task.py").write_text(
        "import sys, json\n"
        "r = json.load(sys.stdin)\n"
        "open('CALLS', 'a', encoding='utf-8').write(r['example_id'] + '\\n')\n"
        "print(json.dumps({'output': {'answer': 'x'}}))\n",
        encoding="utf-8",
    )
    import sys

    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "proposed", "data_policy": "permitted"}],
        "task": {"argv": [sys.executable, "task.py"]},
        "metrics": [
            {
                "name": "shape",
                "evaluator_ref": "structural_shape@1",
                "lens": "non_reference",
                "score_type": "binary",
                "applies_to": {"wf": ["keep"]},
            }
        ],
    }
    run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    calls = (tmp_path / "CALLS").read_text(encoding="utf-8").split()
    assert calls == ["keep1"]  # the selector-excluded output-less subject was never replayed
