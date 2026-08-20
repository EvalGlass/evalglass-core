"""Judge-evidence collection + the no-calibration-record ⇒ UNCALIBRATED rule (EG-M4-1b).

The harness collects judge evidence for metrics that declare ``required_evidence:
["judge"]`` — calling the ``JudgeModel`` per example, **policy-aware** (a source whose
data policy forbids egress is never sent to the judge, exactly like the M2 replay
subprocess), and converts each ``JudgeResult`` into ``JudgeEvidence``.

The cardinal trust rule of this slice: a metric that needs judge evidence but has **no
host-owned calibration record** resolves to ``UNCALIBRATED`` (informational), never
``None`` — so a judge metric can never gate just because the yaml left calibration
unset. Calibration that *can* gate arrives as a validated record in EG-M4-3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters.judge_fake import FakeJudgeModel
from evalglass.core import (
    AuthorityLevel,
    DataPolicy,
    DatasetStatus,
    EvalUnit,
    Example,
    JudgeCalibration,
    JudgeEvidenceStatus,
    UnitKind,
    resolve_authority,
)
from evalglass.harness.config import MetricConfig, RuntimeConfig
from evalglass.harness.judge import collect_judge_evidence
from evalglass.harness.plan import MetricView, build_plan
from evalglass.harness.runner import run_config


def _collect(
    judge: Any, metrics: list[MetricConfig], examples: list[tuple[Example, bool]]
) -> tuple[list[Any], list[Any]]:
    """Drive plan-based judge collection from MetricConfigs + (Example, egress) pairs."""
    views = [
        MetricView(
            name=m.spec.name,
            selector=m.selector,
            is_judge="judge" in m.spec.required_evidence,
            is_reference=m.spec.lens.value == "reference",
            prerequisites=list(m.spec.required_evidence),
        )
        for m in metrics
    ]
    plan = build_plan(run_id="t", subjects_in=examples, metrics=views)
    example_by_subject = {f"s{i}": ex for i, (ex, _eg) in enumerate(examples)}
    evidence, diags, _handled = collect_judge_evidence(judge, plan, example_by_subject)
    return evidence, diags


_JUDGE_SPEC: dict[str, Any] = {
    "name": "faithfulness",
    "evaluator_ref": "judge_score@1",
    "lens": "non_reference",
    "score_type": "continuous",
    "score_range": [0.0, 1.0],
    "required_evidence": ["judge"],
}


def _judge_metric(**overrides: Any) -> MetricConfig:
    return MetricConfig.from_mapping({**_JUDGE_SPEC, **overrides}, 0)


def _non_judge_metric() -> MetricConfig:
    return MetricConfig.from_mapping(
        {
            "name": "exact_match",
            "evaluator_ref": "exact_match@1",
            "lens": "reference",
            "score_type": "binary",
        },
        1,
    )


def _ex(example_id: str, **ctx: Any) -> Example:
    unit = EvalUnit(unit_id=example_id, kind=UnitKind.CALL, trace_id="t")
    return Example(example_id=example_id, input="q", output="a", unit=unit, context=ctx)


# --- collection: route + policy-aware no-call -------------------------------


def test_collects_evidence_for_judge_metrics_only() -> None:
    judge = FakeJudgeModel(default_value=0.7)
    metrics = [_judge_metric(), _non_judge_metric()]
    evidence, _ = _collect(judge, metrics, [(_ex("e1", judge={"value": 0.9}), True)])
    assert len(evidence) == 1  # only the judge metric contributes evidence
    assert evidence[0].metric == "faithfulness"
    assert evidence[0].status is JudgeEvidenceStatus.OK
    assert evidence[0].parsed_value == pytest.approx(0.9)
    assert evidence[0].response_fingerprint is not None
    assert judge.ledger == [("e1", "faithfulness")]


def test_forbidden_egress_makes_no_judge_call() -> None:
    judge = FakeJudgeModel(default_value=0.7)
    evidence, diags = _collect(judge, [_judge_metric()], [(_ex("e1", judge={"value": 0.9}), False)])
    assert judge.ledger == []  # data policy forbids egress: the judge was NOT called
    assert evidence[0].status is JudgeEvidenceStatus.MISSING
    assert evidence[0].parsed_value is None
    assert diags  # a diagnostic explains the egress refusal


def test_failure_evidence_carries_no_value() -> None:
    evidence, _ = _collect(
        FakeJudgeModel(), [_judge_metric()], [(_ex("e1", judge={"mode": "timeout"}), True)]
    )
    assert evidence[0].status is JudgeEvidenceStatus.TIMEOUT
    assert evidence[0].parsed_value is None


# --- the no-calibration-record ⇒ UNCALIBRATED rule --------------------------


def test_judge_metric_defaults_to_uncalibrated() -> None:
    assert _judge_metric().judge_calibration is JudgeCalibration.UNCALIBRATED


def test_non_judge_metric_has_no_judge_calibration() -> None:
    assert _non_judge_metric().judge_calibration is None


def test_explicit_calibration_is_preserved() -> None:
    assert _judge_metric(judge_calibration="calibrated").judge_calibration is (
        JudgeCalibration.CALIBRATED
    )


def test_uncalibrated_judge_metric_cannot_gate() -> None:
    metric = _judge_metric(metric_status="gating", threshold_approval="approved", threshold=0.5)
    resolved = resolve_authority(
        metric.authority_inputs(
            dataset_status=DatasetStatus.VALIDATED, data_policy=DataPolicy.PERMITTED
        )
    )
    assert resolved.level is AuthorityLevel.INFORMATIONAL
    assert not resolved.can_gate


# --- run_config wiring: the judge route runs and cannot gate uncalibrated ---


def test_run_config_uncalibrated_judge_metric_is_informational(tmp_path: Path) -> None:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a", "reference": "a"}) + "\n",
        encoding="utf-8",
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": {"adapter": "fake", "default_value": 1.0},
        "metrics": [
            {
                "name": "exact_match",
                "evaluator_ref": "exact_match@1",
                "lens": "reference",
                "score_type": "binary",
                "required_evidence": ["judge"],
                "metric_status": "gating",
                "threshold_approval": "approved",
                "threshold": 0.5,
            }
        ],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    authority = record.scorecard.authority["exact_match"]
    assert authority.level is AuthorityLevel.INFORMATIONAL  # UNCALIBRATED judge cannot gate
    assert not authority.can_gate


def test_judge_default_value_enters_provenance(tmp_path: Path) -> None:
    # a judge-adapter setting changes the collected evidence/scores, so it must break
    # baseline comparability — two runs differing only in judge.default_value must not match.
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a", "reference": "a"}) + "\n",
        encoding="utf-8",
    )

    def _provenance(default_value: float) -> Any:
        raw: dict[str, Any] = {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "judge": {"adapter": "fake", "default_value": default_value},
            "metrics": [
                {
                    "name": "exact_match",
                    "evaluator_ref": "exact_match@1",
                    "lens": "reference",
                    "score_type": "binary",
                    "required_evidence": ["judge"],
                }
            ],
        }
        return run_config(RuntimeConfig.from_mapping(raw), tmp_path).provenance

    assert _provenance(1.0) != _provenance(0.5)


def test_judge_score_pipeline_gates_on_a_calibrated_judge(tmp_path: Path) -> None:
    # the whole pipeline: a real MEASUREMENT judge (a host command subprocess) -> JudgeEvidence ->
    # judge_score evaluator -> a calibrated, approved gate -> PASS (0.8 clears the approved 0.5).
    # A fake judge could NOT gate here (EG-NR-1) — only a measurement instrument earns authority.
    import sys

    from evalglass.core import Verdict

    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a"}) + "\n", encoding="utf-8"
    )
    (tmp_path / "judges").mkdir()
    (tmp_path / "judges" / "j.py").write_text(
        "import sys, json\njson.load(sys.stdin)\n"
        "print(json.dumps({'value': 0.8, 'rationale': 'ok'}))\n",
        encoding="utf-8",
    )
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "faithfulness.json").write_text(
        json.dumps(
            {
                "calibration": {
                    "status": "calibrated",
                    "approver": "alice",
                    "rationale": "labels",
                    "variance_runs": 5,
                },
                "threshold": {
                    "value": 0.5,
                    "direction": "higher_is_better",
                    "variance": 0.05,
                    "approver": "alice",
                    "rationale": "p95",
                    "version": "1",
                },
            }
        ),
        encoding="utf-8",
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": {"adapter": "command", "command": [sys.executable, "judges/j.py"]},
        "metrics": [
            {
                "name": "faithfulness",
                "evaluator_ref": "judge_score@1",
                "lens": "non_reference",
                "score_type": "continuous",
                "score_range": [0.0, 1.0],
                "required_evidence": ["judge"],
                "metric_status": "gating",
                "calibration": "calibration/faithfulness.json",
            }
        ],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    assert record.scorecard.authority["faithfulness"].can_gate
    assert record.scorecard.verdict.verdict is Verdict.PASS
