"""The pure core engine + M0 acceptance (EG-M0-6b).

``run_evaluation`` composes the whole effect-free pipeline — evaluators -> scores
-> aggregation -> provenance/comparability -> authority -> the single Verdict
Engine -> RunRecord + Scorecard — with no I/O, network, subprocess, or clock
(``architecture.md §3``). This is the M0 acceptance: fixture examples and
trace-shaped examples produce an honest RunRecord and Scorecard, and an
unauthorized metric stays informational rather than silently gating.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    MetricStatus,
    ThresholdApproval,
)
from evalglass.core.builtins import exact_match
from evalglass.core.contracts import (
    ContractError,
    DataPolicy,
    EvalUnit,
    EvidenceBundle,
    Example,
    UnitKind,
)
from evalglass.core.engine import MetricPlan, run_evaluation
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.provenance import RunFingerprint
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType
from evalglass.core.results import RunRecord
from evalglass.core.scores import Score, ScoreBatch, ScoreStatus, Validity
from evalglass.core.verdict import Verdict

_EVID = EvidenceBundle()
_DIMS = {
    d: f"{d}-v1"
    for d in (
        "framework",
        "metric_spec",
        "evaluator",
        "dataset",
        "example",
        "evidence",
        "config",
        "policy",
        "authority",
        "baseline",
    )
}


def _spec() -> MetricSpec:
    return MetricSpec(
        name="exact_match",
        version="1",
        lens=Lens.REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="exact_match@1",
    )


def _example(
    output: str,
    reference: str,
    *,
    trace_shaped: bool = False,
    example_id: str = "e1",
    unit_id: str = "u1",
) -> Example:
    unit = EvalUnit(
        unit_id=unit_id, kind=UnitKind.CALL, trace_id="trace-7" if trace_shaped else "t1"
    )
    return Example(
        example_id=example_id, input="2+2?", output=output, reference=reference, unit=unit
    )


def _plan(authority: AuthorityInputs, threshold: float | None = 0.5) -> MetricPlan:
    return MetricPlan(
        spec=_spec(), evaluator=exact_match.evaluate, authority=authority, threshold=threshold
    )


def _gating_authority() -> AuthorityInputs:
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=DatasetStatus.VALIDATED,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
    )


def test_passing_run_produces_honest_runrecord() -> None:
    record = run_evaluation(
        run_id="run-1",
        examples=[_example("4", "4"), _example("4", "4", trace_shaped=True)],
        evidence=_EVID,
        plans=[_plan(_gating_authority())],
        dimensions=_DIMS,
    )
    assert isinstance(record, RunRecord)
    assert record.scorecard.verdict.verdict is Verdict.PASS
    assert record.scorecard.verdict.ci_should_fail is False
    assert len(record.scores) == 2  # one score per example
    assert record.scorecard.metrics[0].value == pytest.approx(1.0)
    assert "dimensions" in record.provenance.to_dict()


def test_failing_run_fails_the_gate() -> None:
    record = run_evaluation(
        run_id="run-2",
        examples=[_example("5", "4")],  # mismatch -> 0.0, below 0.5 threshold
        evidence=_EVID,
        plans=[_plan(_gating_authority())],
        dimensions=_DIMS,
    )
    assert record.scorecard.verdict.verdict is Verdict.FAIL
    assert record.scorecard.verdict.ci_should_fail is True


def test_unauthorized_metric_stays_informational() -> None:
    draft = AuthorityInputs(
        metric_status=MetricStatus.DRAFT,
        dataset_status=DatasetStatus.PROPOSED,
        threshold_approval=ThresholdApproval.PROPOSED,
        data_policy=DataPolicy.PERMITTED,
    )
    record = run_evaluation(
        run_id="run-3",
        examples=[_example("5", "4")],  # would fail if it were gating
        evidence=_EVID,
        plans=[_plan(draft)],
        dimensions=_DIMS,
    )
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
    assert record.scorecard.verdict.ci_should_fail is False


def test_engine_is_deterministic() -> None:
    def _run() -> RunRecord:
        return run_evaluation(
            run_id="r",
            examples=[_example("4", "4")],
            evidence=_EVID,
            plans=[_plan(_gating_authority())],
            dimensions=_DIMS,
        )

    assert _run() == _run()


def test_runrecord_round_trips_through_json() -> None:
    record = run_evaluation(
        run_id="run-4",
        examples=[_example("4", "4")],
        evidence=_EVID,
        plans=[_plan(_gating_authority())],
        dimensions=_DIMS,
    )
    assert RunRecord.from_dict(json.loads(json.dumps(record.to_dict()))) == record


def test_active_gate_with_incomplete_measurement_blocks() -> None:
    """A gating metric with a non_evaluable example must block, not pass on the valid subset."""
    no_ref = Example(
        example_id="e2",
        input="open?",
        output="anything",
        reference=None,  # exact_match -> non_evaluable
        unit=EvalUnit(unit_id="u2", kind=UnitKind.CALL, trace_id="t1"),
    )
    record = run_evaluation(
        run_id="run-5",
        examples=[_example("4", "4"), no_ref],
        evidence=_EVID,
        plans=[_plan(_gating_authority())],
        dimensions=_DIMS,
    )
    assert record.scorecard.verdict.verdict is Verdict.BLOCKED
    assert record.scorecard.metrics[0].status_counts.get("non_evaluable") == 1


def test_engine_overrides_stale_baseline_state() -> None:
    """A regression gate uses the engine-computed comparability, not a stale input."""
    regression = AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=DatasetStatus.VALIDATED,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        requires_baseline=True,
        baseline_state=None,  # caller may even leave it unset; the engine computes it
    )
    # A baseline whose gating dimensions differ -> genuinely not comparable.
    stale_baseline = RunFingerprint.of({**_DIMS, "dataset": "dataset-OLD"})
    record = run_evaluation(
        run_id="run-6",
        examples=[_example("4", "4")],
        evidence=_EVID,
        plans=[_plan(regression)],
        dimensions=_DIMS,
        baseline=stale_baseline,
        comparison_requested=True,
    )
    # not comparable -> the regression gate blocks despite a perfect score
    assert record.scorecard.verdict.verdict is Verdict.BLOCKED


def test_evaluator_emitting_undeclared_metric_fails_closed() -> None:
    def rogue(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
        del example, context, evidence
        return Score(
            metric="hallucinated",  # not declared by the spec (emits=["exact_match"])
            value=1.0,
            status=ScoreStatus.SCORED,
            validity=Validity.VALID,
            evaluator_version="rogue@1",
        )

    plan = MetricPlan(spec=_spec(), evaluator=rogue, authority=_gating_authority(), threshold=0.5)
    with pytest.raises(ContractError):
        run_evaluation(
            run_id="run-7",
            examples=[_example("4", "4")],
            evidence=_EVID,
            plans=[plan],
            dimensions=_DIMS,
        )


def test_evaluator_out_of_range_value_fails_closed() -> None:
    continuous = MetricSpec(
        name="exact_match",
        version="1",
        lens=Lens.REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.CONTINUOUS,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="exact_match@1",
        score_range=(0.0, 1.0),
    )

    def out_of_range(
        example: Example, context: EvaluatorContext, evidence: EvidenceBundle
    ) -> Score:
        del example, context, evidence
        return Score(
            metric="exact_match",
            value=999.0,  # outside [0, 1]
            status=ScoreStatus.SCORED,
            validity=Validity.VALID,
            evaluator_version="oops@1",
        )

    plan = MetricPlan(
        spec=continuous, evaluator=out_of_range, authority=_gating_authority(), threshold=0.5
    )
    with pytest.raises(ContractError):
        run_evaluation(
            run_id="run-8",
            examples=[_example("4", "4")],
            evidence=_EVID,
            plans=[plan],
            dimensions=_DIMS,
        )


def test_score_batch_evidence_refs_are_preserved() -> None:
    def batch_eval(
        example: Example, context: EvaluatorContext, evidence: EvidenceBundle
    ) -> ScoreBatch:
        del example, evidence
        score = Score(
            metric=context.spec.name,
            value=1.0,
            status=ScoreStatus.SCORED,
            validity=Validity.VALID,
            evaluator_version="batch@1",
        )
        return ScoreBatch(evaluator="batch@1", scores=[score], evidence_refs=["judge:shared:1"])

    plan = MetricPlan(
        spec=_spec(), evaluator=batch_eval, authority=_gating_authority(), threshold=0.5
    )
    record = run_evaluation(
        run_id="run-9",
        examples=[_example("4", "4")],
        evidence=_EVID,
        plans=[plan],
        dimensions=_DIMS,
    )
    assert "judge:shared:1" in record.scores[0].evidence_refs
    # F1/ADR 0024: a batch member is stamped with the example identity too, without
    # dropping the evaluator's shared evidence ref.
    assert record.scores[0].example_id == "e1"
    assert record.scores[0].unit_id == "u1"


# --- F1: the engine stamps subject identity on every score (ADR 0024) -------


def test_engine_stamps_and_groups_subject_identity() -> None:
    """Every score carries its subject; scores group by explicit identity, not list order —
    and that identity survives the runrecord.json round-trip (the by-call enabler)."""
    examples = [
        _example("4", "4", example_id="ex-a", unit_id="u-a"),
        _example("4", "4", example_id="ex-b", unit_id="u-b"),
    ]
    record = run_evaluation(
        run_id="id-1",
        examples=examples,
        evidence=_EVID,
        plans=[_plan(_gating_authority())],
        dimensions=_DIMS,
    )
    by_call = {s.example_id: s for s in record.scores}
    assert set(by_call) == {"ex-a", "ex-b"}  # grouped by explicit identity
    assert by_call["ex-a"].unit_id == "u-a"
    restored = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert {(s.example_id, s.unit_id) for s in restored.scores} == {
        ("ex-a", "u-a"),
        ("ex-b", "u-b"),
    }


def test_core_public_exports_present() -> None:
    import evalglass.core as core

    for name in (
        "Example",
        "Score",
        "MetricSpec",
        "RunRecord",
        "Scorecard",
        "VerdictPayload",
        "run_evaluation",
    ):
        assert hasattr(core, name), f"evalglass.core must export {name}"
