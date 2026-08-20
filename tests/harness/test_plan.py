"""The typed EvaluationPlan + pure planner.

Proves the plan reconciles population exactly, reuses the one ``ExampleSelector`` implementation,
bypasses selectors for integrity subjects, plans exactly the eligible effects, resolves data policy
fail-closed, round-trips through JSON, and fails closed on a malformed record.
"""

from __future__ import annotations

import pytest

from evalglass.core import ContractError, EvalUnit, Example, UnitKind
from evalglass.core.selector import INTEGRITY_METADATA_KEY, ExampleSelector
from evalglass.harness.plan import (
    DeviationCode,
    EffectKind,
    EvaluationPlan,
    MetricView,
    PlannedEffect,
    PolicyDecision,
    build_plan,
)


def _example(
    example_id: str,
    *,
    output: object | None = "out",
    reference: object | None = None,
    metadata: dict[str, object] | None = None,
) -> Example:
    unit = EvalUnit(unit_id=f"{example_id}#u", kind=UnitKind.CALL, trace_id=example_id)
    return Example(
        example_id=example_id,
        input="in",
        output=output,
        reference=reference,
        unit=unit,
        metadata=metadata or {},
    )


def _runtime_metric(name: str, selector: ExampleSelector | None = None) -> MetricView:
    return MetricView(
        name=name, selector=selector, is_judge=False, is_reference=False, prerequisites=[]
    )


def _judge_metric(name: str, selector: ExampleSelector | None = None) -> MetricView:
    return MetricView(
        name=name,
        selector=selector,
        is_judge=True,
        is_reference=False,
        prerequisites=["judge"],
        rubric_ref="rubrics/r.md",
    )


def _reference_metric(name: str) -> MetricView:
    return MetricView(
        name=name, selector=None, is_judge=False, is_reference=True, prerequisites=["reference"]
    )


def test_every_metric_appears_including_zero_match() -> None:
    subjects = [(_example("a", metadata={"wf": "x"}), True)]
    sel = ExampleSelector.from_dict({"wf": ["nope"]})
    plan = build_plan(
        run_id="r", subjects_in=subjects, metrics=[_runtime_metric("m", selector=sel)]
    )
    assert [pm.metric for pm in plan.metrics] == ["m"]
    pm = plan.metrics[0]
    assert pm.available == 1
    assert pm.selector_matched == 0
    assert pm.eligible == 0
    assert pm.excluded == {"selector_mismatch": 1}


def test_population_conserves_with_selector() -> None:
    subs = [
        (_example("a", metadata={"wf": "keep"}), True),
        (_example("b", metadata={"wf": "drop"}), True),
        (_example("c", metadata={"wf": "keep"}), True),
    ]
    sel = ExampleSelector.from_dict({"wf": ["keep"]})
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_runtime_metric("m", selector=sel)])
    pm = plan.metrics[0]
    # available == selector_matched + selector_mismatch; matched == eligible (no prereq loss)
    assert pm.available == 3
    assert pm.selector_matched == 2
    assert pm.eligible == 2
    assert pm.excluded == {"selector_mismatch": 1}
    assert pm.available == pm.selector_matched + pm.excluded.get("selector_mismatch", 0)


def test_stable_ids_survive_colliding_example_ids() -> None:
    subs = [(_example("dup"), True), (_example("dup"), True)]
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_runtime_metric("m")])
    ids = [s.subject_id for s in plan.subjects]
    assert ids == ["s0", "s1"]  # unique despite colliding host example_id
    assert all(s.example_id == "dup" for s in plan.subjects)


def test_integrity_subject_bypasses_selector_and_plans_no_judge_egress() -> None:
    integrity = _example("__integ__", output=None, metadata={INTEGRITY_METADATA_KEY: True})
    ordinary = _example("a", metadata={"wf": "x"})
    subs = [(ordinary, True), (integrity, True)]
    sel = ExampleSelector.from_dict({"wf": ["other"]})  # excludes the ordinary one
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_judge_metric("j", selector=sel)])
    pm = plan.metrics[0]
    # ordinary excluded by selector, integrity always matches+eligible
    assert pm.selector_matched == 1
    assert pm.eligible == 1
    # but integrity causes NO external judge effect
    assert plan.judge_effects() == []


def test_judge_effects_one_per_eligible_subject() -> None:
    subs = [(_example("a"), True), (_example("b"), True), (_example("c"), True)]
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_judge_metric("j")])
    effects = plan.judge_effects()
    assert len(effects) == 3
    assert {e.effect_id for e in effects} == {"judge:j:s0", "judge:j:s1", "judge:j:s2"}
    assert all(e.metric == "j" and e.instrument_ref == "rubrics/r.md" for e in effects)
    assert plan.metrics[0].effect_ids == ["judge:j:s0", "judge:j:s1", "judge:j:s2"]


def test_forbidden_policy_marks_effect_denied() -> None:
    subs = [(_example("a"), False)]  # egress not ok
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_judge_metric("j")])
    effect = plan.judge_effects()[0]
    assert effect.policy_decision is PolicyDecision.DENIED
    assert plan.subjects[0].policy_decision is PolicyDecision.DENIED


def test_reference_metric_missing_reference_is_prereq_exclusion() -> None:
    subs = [
        (_example("a", reference="gold"), True),
        (_example("b", reference=None), True),
    ]
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_reference_metric("ref")])
    pm = plan.metrics[0]
    assert pm.selector_matched == 2
    assert pm.eligible == 1
    assert pm.excluded == {"missing_prerequisite": 1}
    assert pm.selector_matched == pm.eligible + pm.excluded["missing_prerequisite"]


def test_replay_effect_for_missing_output_only() -> None:
    subs = [
        (_example("a", output=None), True),
        (_example("b", output="present"), True),
    ]
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_runtime_metric("m")])
    replay = plan.replay_effects()
    assert [e.subject_id for e in replay] == ["s0"]
    assert replay[0].effect_id == "replay:s0"
    assert replay[0].metric is None


def test_no_replay_for_integrity_subject() -> None:
    integrity = _example("__integ__", output=None, metadata={INTEGRITY_METADATA_KEY: True})
    plan = build_plan(run_id="r", subjects_in=[(integrity, True)], metrics=[_runtime_metric("m")])
    assert plan.replay_effects() == []


def test_no_selector_config_matches_every_subject() -> None:
    subs = [(_example("a"), True), (_example("b"), True)]
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_runtime_metric("m")])
    pm = plan.metrics[0]
    assert pm.selector is None
    assert pm.available == pm.selector_matched == pm.eligible == 2
    assert pm.excluded == {}


def test_fingerprint_changes_with_selector_stable_for_cosmetic() -> None:
    subs = [(_example("a", metadata={"wf": "x"}), True)]
    base = build_plan(run_id="r", subjects_in=subs, metrics=[_runtime_metric("m")])
    sel = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[_runtime_metric("m", selector=ExampleSelector.from_dict({"wf": ["x"]}))],
    )
    assert base.fingerprint() != sel.fingerprint()  # selector is score-determining
    # A cosmetic-only change (the run_id label) does not move the digest — same subjects/metrics.
    cosmetic = build_plan(run_id="OTHER-LABEL", subjects_in=subs, metrics=[_runtime_metric("m")])
    assert base.fingerprint() == cosmetic.fingerprint()


def test_fingerprint_changes_with_policy() -> None:
    ok = build_plan(run_id="r", subjects_in=[(_example("a"), True)], metrics=[_judge_metric("j")])
    denied = build_plan(
        run_id="r", subjects_in=[(_example("a"), False)], metrics=[_judge_metric("j")]
    )
    assert ok.fingerprint() != denied.fingerprint()


def test_round_trip_json() -> None:
    subs = [
        (_example("a", output=None, metadata={"wf": "x"}), True),
        (_example("b", reference="g"), False),
    ]
    plan = build_plan(
        run_id="run-1",
        subjects_in=subs,
        metrics=[
            _judge_metric("j", selector=ExampleSelector.from_dict({"wf": ["x"]})),
            _reference_metric("ref"),
        ],
    )
    restored = EvaluationPlan.from_dict(plan.to_dict())
    assert restored.to_dict() == plan.to_dict()
    assert restored.fingerprint() == plan.fingerprint()


def test_reconcile_reports_both_deviation_kinds() -> None:
    subs = [(_example("a"), True), (_example("b"), True)]
    plan = build_plan(run_id="r", subjects_in=subs, metrics=[_judge_metric("j")])
    # planned: judge:j:s0, judge:j:s1. Executed: s0 only + a rogue extra.
    deviations = plan.reconcile(["judge:j:s0", "judge:j:ROGUE"])
    codes = {(d.code, d.effect_id) for d in deviations}
    assert (DeviationCode.EXECUTED_NOT_PLANNED, "judge:j:ROGUE") in codes
    assert (DeviationCode.PLANNED_NOT_EXECUTED, "judge:j:s1") in codes


def test_from_dict_fails_closed_on_missing_field() -> None:
    with pytest.raises(ContractError):
        PlannedEffect.from_dict({"effect_id": "e", "kind": "judge"})  # missing subject_id/policy


def test_from_dict_rejects_bad_enum() -> None:
    with pytest.raises(ContractError):
        EvaluationPlan.from_dict(
            {
                "run_id": "r",
                "subjects": [],
                "metrics": [],
                "effects": [
                    {
                        "effect_id": "e",
                        "kind": "NOPE",
                        "subject_id": "s0",
                        "policy_decision": "permitted",
                    }
                ],
            }
        )


def test_planner_is_pure_no_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    # A static-ish guard: the planner must not import or use subprocess/socket. Assert the module
    # has no such names bound (belt-and-braces beside the architecture import guard test).
    import evalglass.harness.plan as plan_mod

    for forbidden in ("subprocess", "socket", "urllib", "time"):
        assert not hasattr(plan_mod, forbidden), f"planner must not use {forbidden}"
    # Building a plan returns without any effect; effects are plan records, not executions.
    result = build_plan(
        run_id="r", subjects_in=[(_example("a"), True)], metrics=[_judge_metric("j")]
    )
    assert isinstance(result.judge_effects()[0], PlannedEffect)
    assert EffectKind.JUDGE.value == "judge"
