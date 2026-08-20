"""Engine-level behaviour of per-metric example selectors (EG-V02-4 / K2).

A metric with an ``ExampleSelector`` scores only the examples it matches — so one run of a
multi-call-site suite yields a per-call-site scorecard instead of cross-contaminated numbers.
Two honesty properties are asserted: a selector that matches nothing produces a visible
``non_evaluable`` (never a vacuous pass), and an integrity example is always scored (so an
incomplete-input run still blocks a selector-scoped gate).
"""

from __future__ import annotations

from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    MetricStatus,
    ThresholdApproval,
)
from evalglass.core.builtins import structural_shape
from evalglass.core.contracts import DataPolicy, EvalUnit, EvidenceBundle, Example, UnitKind
from evalglass.core.engine import MetricPlan, run_evaluation
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType
from evalglass.core.results import RunRecord
from evalglass.core.scores import ScoreStatus
from evalglass.core.selector import INTEGRITY_METADATA_KEY, ExampleSelector

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
        name="shape",
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="structural_shape@1",
    )


def _informational() -> AuthorityInputs:
    return AuthorityInputs(
        metric_status=MetricStatus.INFORMATIONAL,
        dataset_status=DatasetStatus.PROPOSED,
        threshold_approval=ThresholdApproval.PROPOSED,
        data_policy=DataPolicy.PERMITTED,
    )


def _ex(eid: str, metadata: dict[str, object]) -> Example:
    unit = EvalUnit(unit_id=eid, kind=UnitKind.CALL, trace_id=eid)
    return Example(example_id=eid, input="i", output={"ok": True}, unit=unit, metadata=metadata)


def _plan(selector: ExampleSelector | None) -> MetricPlan:
    return MetricPlan(
        spec=_spec(),
        evaluator=structural_shape.evaluate,
        authority=_informational(),
        selector=selector,
    )


def _run(examples: list[Example], selector: ExampleSelector | None) -> RunRecord:
    return run_evaluation(
        run_id="r",
        examples=examples,
        evidence=EvidenceBundle(),
        plans=[_plan(selector)],
        dimensions=_DIMS,
    )


def test_selector_scores_only_matching_examples() -> None:
    examples = [
        _ex("a1", {"workflow": "a"}),
        _ex("b1", {"workflow": "b"}),
        _ex("a2", {"workflow": "a"}),
    ]
    rec = _run(examples, ExampleSelector(constraints={"workflow": ("a",)}))
    metric = rec.scorecard.metrics[0]
    assert metric.included_count == 2  # only the two workflow=a examples
    scored_ids = {s.example_id for s in rec.scores if s.status is ScoreStatus.SCORED}
    assert scored_ids == {"a1", "a2"}


def test_no_selector_scores_every_example_backward_compatible() -> None:
    examples = [_ex("a1", {"workflow": "a"}), _ex("b1", {"workflow": "b"})]
    rec = _run(examples, None)
    assert rec.scorecard.metrics[0].included_count == 2


def test_selector_matching_nothing_is_non_evaluable_not_vacuous() -> None:
    examples = [_ex("a1", {"workflow": "a"})]
    rec = _run(examples, ExampleSelector(constraints={"workflow": ("nope",)}))
    metric = rec.scorecard.metrics[0]
    assert metric.included_count == 0
    assert metric.value is None
    # a single honest non_evaluable with a visible reason, not a silent absence or a 0.0
    assert metric.status_counts.get("non_evaluable") == 1
    codes = [d.code for s in rec.scores for d in s.diagnostics]
    assert "selector.no_match" in codes


def test_integrity_example_bypasses_the_selector() -> None:
    # An integrity example (metadata flag) is scored even though it lacks the selector's key.
    integrity = _ex("integrity", {INTEGRITY_METADATA_KEY: True})
    rec = _run([integrity], ExampleSelector(constraints={"workflow": ("a",)}))
    assert rec.scorecard.metrics[0].included_count == 1
    assert {s.example_id for s in rec.scores if s.status is ScoreStatus.SCORED} == {"integrity"}
