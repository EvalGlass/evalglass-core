"""EGTS-M0 core proof — the verdict matrix proven through the real product surface.

These scenarios drive the *real* ``evalglass.core.run_evaluation`` (no shortcuts)
and compare the emitted RunRecord/Scorecard to **declared** expectations via the
EGTS checkers, which never recompute the verdict (``tests/CLAUDE.md §2/§4``). Each
checker family carries a negative control: a declared expectation that disagrees
with honest product output must make the checker fail, proving it is a real check
and not a rubber stamp. Covers EGTS-M0-3 (contracts), -M0-4 (score states),
-M0-5 (evaluator/registry), -M0-6 (verdict matrix).
"""

from __future__ import annotations

import json

import pytest

from evalglass.core import (
    AuthorityInputs,
    DataPolicy,
    DatasetStatus,
    Direction,
    EvalUnit,
    EvidenceBundle,
    Example,
    Lens,
    MetricPlan,
    MetricSpec,
    MetricStatus,
    RunFingerprint,
    RunRecord,
    ScoreType,
    ThresholdApproval,
    UnitKind,
    Verdict,
    run_evaluation,
)
from evalglass.core.builtins import exact_match
from tests.egts.checkers import CheckerError, check_exit_class, check_verdict

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


def _example(output: str, reference: str | None) -> Example:
    return Example(
        example_id="e1",
        input="q",
        output=output,
        reference=reference,
        unit=EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1"),
    )


def _authority(**over: object) -> AuthorityInputs:
    base: dict[str, object] = {
        "metric_status": MetricStatus.GATING,
        "dataset_status": DatasetStatus.VALIDATED,
        "threshold_approval": ThresholdApproval.APPROVED,
        "data_policy": DataPolicy.PERMITTED,
    }
    base.update(over)
    return AuthorityInputs(**base)  # type: ignore[arg-type]


def _run(examples: list[Example], authority: AuthorityInputs, threshold: float | None) -> RunRecord:
    plan = MetricPlan(
        spec=_spec(), evaluator=exact_match.evaluate, authority=authority, threshold=threshold
    )
    return run_evaluation(
        run_id="proof",
        examples=examples,
        evidence=_EVID,
        plans=[plan],
        dimensions=_DIMS,
    )


# --- the verdict matrix, through the real engine ----------------------------


def test_proof_informational() -> None:
    record = _run([_example("4", "4")], _authority(metric_status=MetricStatus.DRAFT), 0.5)
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)
    check_exit_class(record.scorecard, expected="zero")


def test_proof_pass() -> None:
    record = _run([_example("4", "4")], _authority(), 0.5)
    check_verdict(record.scorecard, expected=Verdict.PASS)
    check_exit_class(record.scorecard, expected="zero")


def test_proof_fail() -> None:
    record = _run([_example("5", "4")], _authority(), 0.5)
    check_verdict(record.scorecard, expected=Verdict.FAIL)
    check_exit_class(record.scorecard, expected="nonzero_fail")


def test_proof_blocked_on_policy() -> None:
    record = _run([_example("4", "4")], _authority(data_policy=DataPolicy.FORBIDDEN), 0.5)
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)
    check_exit_class(record.scorecard, expected="nonzero_blocked")


def test_proof_score_state_blocks_on_incomplete() -> None:
    # one referenced (scored) + one without a reference (non_evaluable) -> blocked
    record = _run([_example("4", "4"), _example("x", None)], _authority(), 0.5)
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)
    assert record.scorecard.metrics[0].status_counts.get("non_evaluable") == 1


def test_proof_comparability_blocks_regression() -> None:
    """A regression gate with a non-comparable baseline blocks, through the real engine."""
    regression = _authority(requires_baseline=True)
    stale = RunFingerprint.of({**_DIMS, "dataset": "dataset-OLD"})  # gating dim differs
    record = run_evaluation(
        run_id="proof",
        examples=[_example("4", "4")],
        evidence=_EVID,
        plans=[
            MetricPlan(
                spec=_spec(),
                evaluator=exact_match.evaluate,
                authority=regression,
                threshold=0.5,
            )
        ],
        dimensions=_DIMS,
        baseline=stale,
        comparison_requested=True,
    )
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)


# --- contract proof: the real artifact round-trips --------------------------


def test_proof_runrecord_is_jsonable_and_round_trips() -> None:
    record = _run([_example("4", "4")], _authority(), 0.5)
    text = json.dumps(record.to_dict())  # primary artifact is plain JSON
    assert RunRecord.from_dict(json.loads(text)) == record


# --- negative controls: the checkers must be able to fail -------------------


def test_checker_fails_on_wrong_declared_verdict() -> None:
    """A declared verdict that disagrees with honest product output must fail."""
    record = _run([_example("4", "4")], _authority(), 0.5)  # really a PASS
    with pytest.raises(CheckerError):
        check_verdict(record.scorecard, expected=Verdict.FAIL)


def test_checker_fails_on_wrong_declared_exit_class() -> None:
    record = _run([_example("5", "4")], _authority(), 0.5)  # really nonzero_fail
    with pytest.raises(CheckerError):
        check_exit_class(record.scorecard, expected="zero")


def test_checker_accepts_scenario_enum_by_value() -> None:
    """A declared verdict from the EGTS scenario enum (a different class) must match."""
    from tests.egts.scenario import Verdict as ScenarioVerdict

    record = _run([_example("4", "4")], _authority(), 0.5)  # a real PASS
    check_verdict(record.scorecard, expected=ScenarioVerdict.PASS)  # must not raise
