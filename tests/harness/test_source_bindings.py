"""Explicit metric source and evidence bindings (Epic D / D1).

A metric may declare which sources provide its candidate/reference/context/observation evidence.
Bindings resolve to known sources or fail closed; a bound metric's population derives only from its
candidate sources plus its selector; an unbound legacy metric keeps the all-source population and
conservative authority. Source roles are domain-neutral and grant no authority.
"""

from __future__ import annotations

import pytest

from evalglass.core import ContractError, EvalUnit, Example, UnitKind
from evalglass.core.selector import INTEGRITY_METADATA_KEY, ExampleSelector
from evalglass.harness.config import RuntimeConfig, SourceBinding, SourceRole
from evalglass.harness.plan import MetricView, build_plan

# --------------------------------------------------------------------------- config binding parse


def _metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "correctness",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
    }
    base.update(over)
    return base


def _cfg(metrics: list[dict[str, object]], **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "metrics": metrics,
        "datasets": [
            {"path": "cand.jsonl", "name": "candidates", "status": "validated"},
            {"path": "gold.jsonl", "name": "reference-set", "status": "validated"},
        ],
    }
    base.update(over)
    return base


def test_bindings_parse_into_typed_source_bindings() -> None:
    cfg = RuntimeConfig.from_mapping(
        _cfg(
            [
                _metric(
                    sources=[
                        {"name": "candidates", "role": "candidate"},
                        {"name": "reference-set", "role": "reference"},
                    ]
                )
            ]
        )
    )
    metric = cfg.metrics[0]
    assert metric.sources == [
        SourceBinding(name="candidates", role=SourceRole.CANDIDATE),
        SourceBinding(name="reference-set", role=SourceRole.REFERENCE),
    ]
    # candidate-only helper drives the planned population
    assert metric.candidate_source_names() == frozenset({"candidates"})


def test_binding_round_trips() -> None:
    binding = SourceBinding(name="candidates", role=SourceRole.CANDIDATE)
    assert SourceBinding.from_mapping(binding.to_dict(), "ctx") == binding


def test_unknown_source_name_fails_closed() -> None:
    cfg = _cfg([_metric(sources=[{"name": "does-not-exist", "role": "candidate"}])])
    with pytest.raises(ContractError, match="unknown source"):
        RuntimeConfig.from_mapping(cfg)


def test_unknown_role_fails_closed() -> None:
    cfg = _cfg([_metric(sources=[{"name": "candidates", "role": "nonsense"}])])
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(cfg)


def test_duplicate_binding_fails_closed() -> None:
    cfg = _cfg(
        [
            _metric(
                sources=[
                    {"name": "candidates", "role": "candidate"},
                    {"name": "candidates", "role": "candidate"},
                ]
            )
        ]
    )
    with pytest.raises(ContractError, match="duplicate"):
        RuntimeConfig.from_mapping(cfg)


def test_sources_without_candidate_fails_closed() -> None:
    cfg = _cfg([_metric(sources=[{"name": "reference-set", "role": "reference"}])])
    with pytest.raises(ContractError, match="candidate"):
        RuntimeConfig.from_mapping(cfg)


def test_dataset_and_sources_together_is_ambiguous() -> None:
    cfg = _cfg(
        [_metric(dataset="candidates", sources=[{"name": "candidates", "role": "candidate"}])]
    )
    with pytest.raises(ContractError, match="dataset"):
        RuntimeConfig.from_mapping(cfg)


def test_ambiguous_source_name_across_kinds_fails_closed() -> None:
    # A name that is both a dataset and a trace cannot be bound unambiguously.
    cfg = {
        "metrics": [_metric(sources=[{"name": "shared", "role": "candidate"}])],
        "datasets": [{"path": "d.jsonl", "name": "shared", "status": "validated"}],
        "traces": [{"path": "t.jsonl", "name": "shared"}],
    }
    with pytest.raises(ContractError, match="ambiguous"):
        RuntimeConfig.from_mapping(cfg)


def test_trace_source_binding_resolves() -> None:
    cfg = RuntimeConfig.from_mapping(
        {
            "metrics": [
                _metric(
                    lens="non_reference", sources=[{"name": "prod-traces", "role": "candidate"}]
                )
            ],
            "traces": [{"path": "t.jsonl", "name": "prod-traces"}],
        }
    )
    assert cfg.metrics[0].candidate_source_names() == frozenset({"prod-traces"})


def test_unbound_metric_has_no_candidate_restriction() -> None:
    cfg = RuntimeConfig.from_mapping(_cfg([_metric(dataset="candidates")]))
    # Legacy `dataset` still resolves and the metric is unbound (all-source population).
    assert cfg.metrics[0].sources == []
    assert cfg.metrics[0].candidate_source_names() is None


# ------------------------------------------------------------------------------- plan scoping


def _example(
    example_id: str, *, reference: object | None = None, meta: dict[str, object] | None = None
) -> Example:
    unit = EvalUnit(unit_id=f"{example_id}#u", kind=UnitKind.CALL, trace_id=example_id)
    return Example(
        example_id=example_id,
        input="in",
        output="out",
        reference=reference,
        unit=unit,
        metadata=meta or {},
    )


def _bound_metric(
    name: str, candidates: set[str], *, selector: ExampleSelector | None = None
) -> MetricView:
    return MetricView(
        name=name,
        selector=selector,
        is_judge=False,
        is_reference=False,
        prerequisites=[],
        candidate_sources=frozenset(candidates),
        source_bindings=[{"name": n, "role": "candidate"} for n in sorted(candidates)],
    )


def test_bound_metric_population_is_only_its_candidate_sources() -> None:
    subs = [(_example("a"), True), (_example("b"), True), (_example("c"), True)]
    source_names = ["candidates", "candidates", "other"]
    plan = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[_bound_metric("m", {"candidates"})],
        source_names=source_names,
    )
    pm = plan.metrics[0]
    # Only the two subjects from the bound candidate source are available/eligible.
    assert pm.available == 2
    assert pm.selector_matched == 2
    assert pm.eligible == 2


def test_unbound_metric_sees_all_sources() -> None:
    subs = [(_example("a"), True), (_example("b"), True)]
    source_names = ["ds1", "ds2"]
    plan = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[
            MetricView(
                name="m", selector=None, is_judge=False, is_reference=False, prerequisites=[]
            )
        ],
        source_names=source_names,
    )
    assert plan.metrics[0].available == 2


def test_integrity_subject_stays_bound_even_off_candidate_source() -> None:
    # An integrity (route-error) subject must remain in a bound metric's population so an active
    # gate still blocks on incomplete evidence (D1 AC5).
    integrity = _example("__integ__", meta={INTEGRITY_METADATA_KEY: True})
    subs = [(_example("a"), True), (integrity, True)]
    source_names = ["candidates", "__integrity__"]
    plan = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[_bound_metric("m", {"candidates"})],
        source_names=source_names,
    )
    pm = plan.metrics[0]
    # one candidate subject + the integrity subject both matched and eligible
    assert pm.selector_matched == 2
    assert pm.eligible == 2


def test_binding_is_score_determining_in_the_plan_fingerprint() -> None:
    subs = [(_example("a"), True), (_example("b"), True)]
    source_names = ["candidates", "other"]
    unbound = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[
            MetricView(
                name="m", selector=None, is_judge=False, is_reference=False, prerequisites=[]
            )
        ],
        source_names=source_names,
    )
    bound = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[_bound_metric("m", {"candidates"})],
        source_names=source_names,
    )
    assert unbound.fingerprint() != bound.fingerprint()


def test_plan_records_resolved_bindings_for_doctor() -> None:
    subs = [(_example("a"), True)]
    plan = build_plan(
        run_id="r",
        subjects_in=subs,
        metrics=[_bound_metric("m", {"candidates"})],
        source_names=["candidates"],
    )
    assert plan.metrics[0].source_bindings == [{"name": "candidates", "role": "candidate"}]
