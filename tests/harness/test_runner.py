"""Route convergence + run orchestration (EG-M1-4).

The runner reads every configured source through its port, converges dataset/trace/mixed
routes into one ``Example`` list, loads evaluators, builds ``MetricPlan``s, and calls the
core ``run_evaluation`` — it never computes scores, authority, or the verdict itself. Route
failures (malformed records) are carried as evidence diagnostics, separate from scores.
Defaults stay informational; authority only gates when the host config grants it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import Example, RunRecord, ScoreStatus, Verdict
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config


def _dataset(tmp_path: Path, lines: list[dict[str, object]], name: str = "d.jsonl") -> None:
    (tmp_path / name).write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def _trace(tmp_path: Path, lines: list[dict[str, object]], name: str = "t.jsonl") -> None:
    (tmp_path / name).write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def _metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
    }
    base.update(over)
    return base


def test_dataset_only_run_is_informational_by_default(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    cfg = RuntimeConfig.from_mapping(
        {"datasets": [{"path": "d.jsonl"}], "metrics": [_metric(dataset="d.jsonl")]}
    )
    record = run_config(cfg, root=tmp_path)
    assert isinstance(record, RunRecord)
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
    assert record.scorecard.verdict.ci_should_fail is False
    assert len(record.scores) == 1


def test_trace_only_run_builds_examples_from_behavior(tmp_path: Path) -> None:
    _trace(tmp_path, [{"trace_id": "t1", "behavior": {"input": "q", "output": "a"}}])
    cfg = RuntimeConfig.from_mapping(
        {"traces": [{"path": "t.jsonl"}], "metrics": [_metric(name="field_presence")]}
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
    assert len(record.scores) == 1


def test_mixed_run_converges_examples_from_both_routes(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    _trace(tmp_path, [{"trace_id": "t1", "behavior": {"input": "q", "output": "a"}}])
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl"}],
            "traces": [{"path": "t.jsonl"}],
            "metrics": [_metric(dataset="d.jsonl")],
        }
    )
    record = run_config(cfg, root=tmp_path)
    # one metric over two examples (dataset + trace) → two scores
    assert len(record.scores) == 2
    # F1/ADR 0024: a real harness run stamps distinct subject identity on each score,
    # and it survives serialization to runrecord.json.
    for score in record.scores:
        assert score.example_id, "harness run left a score without example_id"
        assert score.unit_id, "harness run left a score without unit_id"
    assert len({s.example_id for s in record.scores}) == 2
    restored = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert all(s.example_id for s in restored.scores)


def test_gating_metric_passes_through_runner(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [
                _metric(
                    dataset="d.jsonl",
                    metric_status="gating",
                    threshold_approval="approved",
                    threshold=0.5,
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is Verdict.PASS


def test_gating_metric_fails_below_threshold(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "5", "reference": "4"}])  # mismatch -> 0.0
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [
                _metric(
                    dataset="d.jsonl",
                    metric_status="gating",
                    threshold_approval="approved",
                    threshold=0.5,
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is Verdict.FAIL
    assert record.scorecard.verdict.ci_should_fail is True


def test_malformed_dataset_line_is_evidence_not_score(tmp_path: Path) -> None:
    (tmp_path / "d.jsonl").write_text(
        '{"input":"a","output":"1","reference":"1"}\n{ bad json\n', encoding="utf-8"
    )
    cfg = RuntimeConfig.from_mapping(
        {"datasets": [{"path": "d.jsonl"}], "metrics": [_metric(dataset="d.jsonl")]}
    )
    record = run_config(cfg, root=tmp_path)
    # the good line still scores; the malformed line is a diagnostic, not a score
    assert any(s.status is ScoreStatus.SCORED for s in record.scores)
    assert "dataset_invalid_json" in {d.code for d in record.scorecard.diagnostics}
    # default metric is informational, so an unreadable record does not fabricate a fail
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL


def test_gating_metric_blocks_on_malformed_input(tmp_path: Path) -> None:
    # A validated/permitted gating dataset with one good + one malformed line must NOT pass —
    # the gate cannot make a clean claim over records it could not read.
    (tmp_path / "d.jsonl").write_text(
        '{"input":"2+2","output":"4","reference":"4"}\n{ bad json\n', encoding="utf-8"
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [
                _metric(
                    dataset="d.jsonl",
                    metric_status="gating",
                    threshold_approval="approved",
                    threshold=0.5,
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is Verdict.BLOCKED
    assert record.scorecard.verdict.ci_should_fail is True


def test_gating_metric_does_not_pass_when_trace_dilutes_authority(tmp_path: Path) -> None:
    # A validated dataset mixed with a trace (no validated gold) drops to proposed authority,
    # so the gate cannot pass over the trace examples it also scores.
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    _trace(tmp_path, [{"trace_id": "t1", "behavior": {"input": "q", "output": "a"}}])
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "traces": [{"path": "t.jsonl", "data_policy": "permitted"}],
            "metrics": [
                _metric(
                    dataset="d.jsonl",
                    metric_status="gating",
                    threshold_approval="approved",
                    threshold=0.5,
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is not Verdict.PASS


def test_threshold_change_changes_fingerprint(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])

    def _run(threshold: float) -> RunRecord:
        cfg = RuntimeConfig.from_mapping(
            {
                "datasets": [
                    {"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}
                ],
                "metrics": [
                    _metric(
                        dataset="d.jsonl",
                        metric_status="gating",
                        threshold_approval="approved",
                        threshold=threshold,
                    )
                ],
            }
        )
        return run_config(cfg, root=tmp_path)

    assert (
        _run(0.5).provenance.dimensions["authority"] != _run(0.6).provenance.dimensions["authority"]
    )


def test_requires_baseline_without_baseline_blocks(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "baseline": {"comparison_requested": True},
            "metrics": [
                _metric(
                    dataset="d.jsonl",
                    metric_status="gating",
                    threshold_approval="approved",
                    threshold=0.5,
                    requires_baseline=True,
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is Verdict.BLOCKED
    assert record.scorecard.verdict.ci_should_fail is True


def test_evaluator_receives_example_not_raw_trace(tmp_path: Path) -> None:
    # Route fidelity: the evaluator must receive a core Example built from behavior, never the
    # raw envelope/trace dict. A host evaluator asserts the type and echoes the output.
    (tmp_path / "evaluators").mkdir()
    (tmp_path / "evaluators" / "probe.py").write_text(
        """
from evalglass.core import Example, Score, ScoreStatus, Validity


def evaluate(example, context, evidence):
    assert isinstance(example, Example), type(example)
    value = 1.0 if example.output == "a" else 0.0
    return Score(metric=context.spec.name, value=value, status=ScoreStatus.SCORED,
                 validity=Validity.VALID, evaluator_version="probe@1")
""",
        encoding="utf-8",
    )
    _trace(tmp_path, [{"trace_id": "t1", "behavior": {"input": "q", "output": "a"}}])
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl"}],
            "metrics": [
                _metric(
                    name="probe",
                    evaluator_ref="evaluators/probe.py:evaluate",
                    score_type="continuous",
                    score_range=[0, 1],
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scores[0].value == pytest.approx(1.0)  # probe saw an Example with output "a"


def test_run_record_round_trips(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    cfg = RuntimeConfig.from_mapping(
        {"datasets": [{"path": "d.jsonl"}], "metrics": [_metric(dataset="d.jsonl")]}
    )
    record = run_config(cfg, root=tmp_path)
    text = json.dumps(record.to_dict())
    assert RunRecord.from_dict(json.loads(text)) == record


def test_examples_are_core_example_instances(tmp_path: Path) -> None:
    _dataset(tmp_path, [{"input": "2+2", "output": "4", "reference": "4"}])
    cfg = RuntimeConfig.from_mapping(
        {"datasets": [{"path": "d.jsonl"}], "metrics": [_metric(dataset="d.jsonl")]}
    )
    record = run_config(cfg, root=tmp_path)
    assert isinstance(record, RunRecord)
    assert all(isinstance(s.metric, str) for s in record.scores)
    _ = Example  # imported for the route-fidelity intent


# --- EG-P1-2: config-reachable trajectory/session units ---------------------


def _trajectory_metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "trajectory.shape",
        "evaluator_ref": "trajectory_shape@1",
        "lens": "non_reference",
        "granularity": "trajectory",
        "score_type": "continuous",
        "score_range": [0.0, 1.0],
        "direction": "higher_is_better",
    }
    base.update(over)
    return base


def test_trajectory_unit_yields_one_aggregate_score(tmp_path: Path) -> None:
    """EG-P1-2 sensitivity: a 2-call trace at ``unit: trajectory`` scores ONE aggregate."""
    _trace(
        tmp_path,
        [
            {"trace_id": "t1", "behavior": {"input": "q1", "output": "a"}},
            {"trace_id": "t1", "behavior": {"input": "q2", "output": "b"}},
        ],
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl", "unit": "trajectory"}],
            "metrics": [_trajectory_metric()],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert len(record.scores) == 1
    score = record.scores[0]
    assert score.status is ScoreStatus.SCORED
    assert score.value == pytest.approx(1.0)  # both members produced output
    assert score.example_id == "trajectory:t1"
    assert score.unit_id == "trajectory:t1"


def test_call_unit_is_unchanged_from_default(tmp_path: Path) -> None:
    """EG-P1-2 specificity: absent ``unit:`` and ``unit: call`` are byte-identical (per-call)."""
    _trace(
        tmp_path,
        [
            {"trace_id": "t1", "behavior": {"input": "q1", "output": "a"}},
            {"trace_id": "t1", "behavior": {"input": "q2", "output": "b"}},
        ],
    )

    def _run(trace_over: dict[str, object]) -> RunRecord:
        cfg = RuntimeConfig.from_mapping(
            {
                "traces": [{"path": "t.jsonl", **trace_over}],
                "metrics": [_metric(name="field_presence", evaluator_ref="field_presence@1")],
            }
        )
        return run_config(cfg, root=tmp_path)

    absent = _run({})
    explicit_call = _run({"unit": "call"})
    trajectory = _run({"unit": "trajectory"})

    # Two per-call examples on the CALL path; one aggregate on the trajectory path.
    assert len(absent.scores) == 2
    assert len(explicit_call.scores) == 2
    assert len(trajectory.scores) == 1
    # CALL fingerprint is byte-identical to the pre-P1 (absent) run; trajectory differs.
    assert absent.provenance.dimensions == explicit_call.provenance.dimensions
    assert absent.provenance.dimensions != trajectory.provenance.dimensions


def test_load_trace_units_egress_worst_of_members(tmp_path: Path) -> None:
    """EG-P1-2 egress fail-closed + permit: an aggregate is egress-OK iff every member is."""
    from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
    from evalglass.core import UnitKind
    from evalglass.harness.config import TraceConfig
    from evalglass.harness.runner import _load_trace_units

    _trace(
        tmp_path,
        [
            {
                "trace_id": "ok",
                "behavior": {"input": "q", "output": "a"},
                "data_policy": "permitted",
            },
            {
                "trace_id": "ok",
                "behavior": {"input": "q", "output": "b"},
                "data_policy": "redacted",
            },
            {
                "trace_id": "bad",
                "behavior": {"input": "q", "output": "c"},
                "data_policy": "permitted",
            },
            {
                "trace_id": "bad",
                "behavior": {"input": "q", "output": "d"},
                "data_policy": "forbidden",
            },
        ],
    )
    units = LocalJsonlTraceSource(TraceConfig(path="t.jsonl", name="t"), tmp_path).read().units
    pairs = _load_trace_units(units, UnitKind.TRAJECTORY)
    egress = {ex.unit.trace_id: ok for ex, ok in pairs}
    assert egress == {"ok": True, "bad": False}  # one forbidden member blocks the whole aggregate


def test_load_trace_units_call_path_pairs_per_unit(tmp_path: Path) -> None:
    """EG-P1-2: the CALL branch keeps the exact per-unit egress pairing (specificity)."""
    from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
    from evalglass.core import UnitKind
    from evalglass.harness.config import TraceConfig
    from evalglass.harness.prepare import example_from_trace
    from evalglass.harness.runner import _egress_ok, _load_trace_units

    _trace(
        tmp_path,
        [
            {
                "trace_id": "t1",
                "behavior": {"input": "q", "output": "a"},
                "data_policy": "permitted",
            },
            {
                "trace_id": "t1",
                "behavior": {"input": "q", "output": "b"},
                "data_policy": "forbidden",
            },
        ],
    )
    units = LocalJsonlTraceSource(TraceConfig(path="t.jsonl", name="t"), tmp_path).read().units
    pairs = _load_trace_units(units, UnitKind.CALL)
    expected = [
        (example_from_trace(u).to_dict(), _egress_ok(u.envelope.data_policy)) for u in units
    ]
    assert [(ex.to_dict(), ok) for ex, ok in pairs] == expected


# --- EG-P1-3: aggregate authority stays informational; identity; degenerate honesty ---------


def test_trajectory_run_is_informational_and_cannot_gate(tmp_path: Path) -> None:
    """EG-P1-3: an aggregate run over proposed trace data resolves ``informational``, not a pass."""
    _trace(
        tmp_path,
        [
            {"trace_id": "t1", "behavior": {"input": "q1", "output": "a"}},
            {"trace_id": "t1", "behavior": {"input": "q2", "output": "b"}},
        ],
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl", "unit": "trajectory"}],
            "metrics": [_trajectory_metric()],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
    assert record.scorecard.verdict.ci_should_fail is False
    assert record.scores[0].unit_id == "trajectory:t1"


def test_trajectory_gate_attempt_never_passes(tmp_path: Path) -> None:
    """EG-P1-3 authority guard: an approved gating threshold on proposed trace data cannot pass."""
    _trace(
        tmp_path,
        [
            {
                "trace_id": "t1",
                "behavior": {"input": "q1", "output": "a"},
                "data_policy": "permitted",
            },
            {
                "trace_id": "t1",
                "behavior": {"input": "q2", "output": "b"},
                "data_policy": "permitted",
            },
        ],
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl", "unit": "trajectory", "data_policy": "permitted"}],
            "metrics": [
                _trajectory_metric(
                    metric_status="gating",
                    threshold_approval="approved",
                    threshold=0.5,
                )
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    # The score itself is a perfect 1.0, but proposed trace data (no validated gold) means the
    # gate cannot honestly fire — the verdict is never a pass.
    assert record.scorecard.verdict.verdict is not Verdict.PASS


def test_degenerate_all_null_trajectory_is_non_evaluable_not_zero(tmp_path: Path) -> None:
    """EG-P1-3 degenerate: an all-``None``-output trajectory scores ``non_evaluable``, never 0.0."""
    _trace(
        tmp_path,
        [
            {"trace_id": "t1", "behavior": {"input": "q1"}},
            {"trace_id": "t1", "behavior": {"input": "q2"}},
        ],
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl", "unit": "trajectory"}],
            "metrics": [_trajectory_metric()],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert len(record.scores) == 1
    score = record.scores[0]
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None  # never a fabricated 0.0


def test_empty_trace_list_yields_no_aggregate(tmp_path: Path) -> None:
    """EG-P1-3 degenerate: an empty trace file produces no aggregate example (no fabricated 0.0)."""
    (tmp_path / "t.jsonl").write_text("", encoding="utf-8")
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl", "unit": "trajectory"}],
            "metrics": [_trajectory_metric()],
        }
    )
    record = run_config(cfg, root=tmp_path)
    # No units → no aggregate Example → the only score (if any) is never a fabricated 0.0.
    assert all(s.value != 0.0 for s in record.scores)
    assert not any(
        s.status is ScoreStatus.SCORED and s.metric == "trajectory.shape" for s in record.scores
    )
