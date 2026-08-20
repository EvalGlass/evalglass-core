"""Typed runtime config boundary (EG-M1-1).

The config is host-owned truth parsed at the harness boundary. Two rules dominate:
fail closed on anything malformed (CLAUDE.md §12; M0 lesson — parsing is the #1 bug
class), and **defaults must never grant gating authority** (CLAUDE.md §11; build
contract §2 #9). These tests pin both before the implementation exists.
"""

from __future__ import annotations

import math

import pytest

from evalglass.core import (
    AuthorityLevel,
    ContractError,
    DataPolicy,
    DatasetStatus,
    Direction,
    MetricStatus,
    ScoreType,
    ThresholdApproval,
    UnitKind,
    resolve_authority,
)
from evalglass.harness.config import RuntimeConfig


def _metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
    }
    base.update(over)
    return base


def _config(**over: object) -> dict[str, object]:
    base: dict[str, object] = {"metrics": [_metric()]}
    base.update(over)
    return base


def test_full_config_parses() -> None:
    cfg = RuntimeConfig.from_mapping(
        {
            "run": {"id": "r1"},
            "datasets": [
                {
                    "path": "d.jsonl",
                    "status": "validated",
                    "version": "2",
                    "data_policy": "permitted",
                }
            ],
            "traces": [{"path": "t.jsonl", "format": "openinference", "data_policy": "permitted"}],
            "metrics": [
                _metric(threshold=0.9, metric_status="gating", threshold_approval="approved")
            ],
            "baseline": {"path": "b.json", "comparison_requested": True},
            "output": {"dir": "out"},
        }
    )
    assert cfg.run_id == "r1"
    assert cfg.output_dir == "out"
    assert cfg.comparison_requested is True
    assert cfg.baseline_path == "b.json"
    assert len(cfg.datasets) == 1
    assert cfg.datasets[0].status is DatasetStatus.VALIDATED
    assert cfg.datasets[0].data_policy is DataPolicy.PERMITTED
    assert len(cfg.traces) == 1
    assert len(cfg.metrics) == 1
    assert cfg.metrics[0].spec.name == "exact_match"
    assert cfg.metrics[0].spec.score_type is ScoreType.BINARY
    assert cfg.metrics[0].threshold == pytest.approx(0.9)


def test_metric_defaults_do_not_grant_gating_authority() -> None:
    """The headline trust rule: a metric with no authority fields cannot gate —
    even when its dataset is validated and policy permits. Defaults stay informational."""
    cfg = RuntimeConfig.from_mapping(_config())
    mc = cfg.metrics[0]
    assert mc.metric_status is MetricStatus.INFORMATIONAL
    assert mc.threshold_approval is ThresholdApproval.PROPOSED
    assert mc.threshold is None
    resolved = resolve_authority(
        mc.authority_inputs(
            dataset_status=DatasetStatus.VALIDATED, data_policy=DataPolicy.PERMITTED
        )
    )
    assert resolved.can_gate is False
    assert resolved.level is AuthorityLevel.INFORMATIONAL


def test_dataset_defaults_are_conservative() -> None:
    cfg = RuntimeConfig.from_mapping(_config(datasets=[{"path": "d.jsonl"}]))
    ds = cfg.datasets[0]
    assert ds.status is DatasetStatus.PROPOSED
    assert ds.data_policy is DataPolicy.UNKNOWN


def test_metric_spec_defaults() -> None:
    cfg = RuntimeConfig.from_mapping(_config())
    spec = cfg.metrics[0].spec
    assert spec.version == "1"
    assert spec.direction is Direction.HIGHER_IS_BETTER


def test_trace_default_format_is_local() -> None:
    cfg = RuntimeConfig.from_mapping(_config(traces=[{"path": "t.jsonl"}]))
    assert cfg.traces[0].fmt.value == "local"


def test_trace_default_unit_is_call() -> None:
    """EG-P1-1: absent ``unit:`` ⇒ CALL, so every pre-P1 trace config is unchanged."""
    cfg = RuntimeConfig.from_mapping(_config(traces=[{"path": "t.jsonl"}]))
    assert cfg.traces[0].kind is UnitKind.CALL


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("call", UnitKind.CALL),
        ("step", UnitKind.STEP),
        ("trajectory", UnitKind.TRAJECTORY),
        ("session", UnitKind.SESSION),
    ],
)
def test_trace_unit_field_parses_every_kind(value: str, expected: UnitKind) -> None:
    """EG-P1-1: all four UnitKind values are accepted at the config layer."""
    cfg = RuntimeConfig.from_mapping(_config(traces=[{"path": "t.jsonl", "unit": value}]))
    assert cfg.traces[0].kind is expected


def test_trace_unknown_unit_fails_closed() -> None:
    """EG-P1-1 negative control: a present-but-bogus ``unit:`` is a setup error, not a default."""
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(traces=[{"path": "t.jsonl", "unit": "bogus"}]))


def test_pre_p1_trace_mapping_parses_unchanged() -> None:
    """EG-P1-1 specificity: a trace config with no ``unit:`` key parses exactly as before."""
    cfg = RuntimeConfig.from_mapping(
        _config(traces=[{"path": "t.jsonl", "name": "t", "data_policy": "permitted"}])
    )
    tr = cfg.traces[0]
    assert (tr.path, tr.name, tr.fmt.value, tr.data_policy.value, tr.kind) == (
        "t.jsonl",
        "t",
        "local",
        "permitted",
        UnitKind.CALL,
    )


def test_run_id_defaults() -> None:
    cfg = RuntimeConfig.from_mapping(_config())
    assert cfg.run_id  # non-empty default
    assert cfg.output_dir == "reports"


# --- fail-closed parsing ----------------------------------------------------


def test_not_a_mapping_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping([1, 2, 3])


def test_no_metrics_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": []})
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({})


def test_missing_required_metric_field_fails() -> None:
    bad = _metric()
    del bad["evaluator_ref"]
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [bad]})


def test_unknown_enum_value_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(datasets=[{"path": "d.jsonl", "data_policy": "nope"}]))
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [_metric(metric_status="supreme")]})


def test_non_finite_threshold_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [_metric(threshold=math.nan)]})
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [_metric(threshold=math.inf)]})


def test_continuous_metric_without_range_fails() -> None:
    # MetricSpec rule reused from M0: a continuous metric must declare a score_range.
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [_metric(score_type="continuous")]})


def test_duplicate_metric_names_fail() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [_metric(), _metric()]})


def test_metric_spec_trust_fields_preserved() -> None:
    # Declared evidence/prereqs/profile must survive into the MetricSpec — dropping
    # them would silently weaken a metric's trust constraints.
    cfg = RuntimeConfig.from_mapping(
        {
            "metrics": [
                _metric(
                    profile={"latency": "low"},
                    required_evidence=["reference"],
                    prerequisites=["structural_ok"],
                )
            ]
        }
    )
    spec = cfg.metrics[0].spec
    assert spec.profile == {"latency": "low"}
    assert spec.required_evidence == ["reference"]
    assert spec.prerequisites == ["structural_ok"]


def test_threshold_outside_score_range_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(
            {"metrics": [_metric(score_type="continuous", score_range=[0, 1], threshold=2)]}
        )
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(
            {"metrics": [_metric(score_type="continuous", score_range=[0, 1], threshold=-0.5)]}
        )


def test_threshold_within_score_range_ok() -> None:
    cfg = RuntimeConfig.from_mapping(
        {"metrics": [_metric(score_type="continuous", score_range=[0, 1], threshold=0.5)]}
    )
    assert cfg.metrics[0].threshold == pytest.approx(0.5)


# --- applies_to / example selector (EG-V02-4 / K2) ---------------------------


def test_applies_to_parses_into_a_selector() -> None:
    cfg = RuntimeConfig.from_mapping(_config(metrics=[_metric(applies_to={"workflow": "extract"})]))
    sel = cfg.metrics[0].selector
    assert sel is not None
    assert sel.to_dict() == {"workflow": ["extract"]}


def test_applies_to_accepts_a_list_of_values() -> None:
    cfg = RuntimeConfig.from_mapping(
        _config(metrics=[_metric(applies_to={"workflow": ["a", "b"]})])
    )
    sel = cfg.metrics[0].selector
    assert sel is not None
    assert sel.to_dict() == {"workflow": ["a", "b"]}


def test_absent_applies_to_is_no_selector_backward_compatible() -> None:
    cfg = RuntimeConfig.from_mapping(_config(metrics=[_metric()]))
    assert cfg.metrics[0].selector is None


def test_applies_to_fails_closed_on_bad_shape() -> None:
    bad_cases: list[object] = [
        {},
        {"workflow": {"nested": 1}},
        {"workflow": []},
        "notamapping",
        {"": "x"},
    ]
    for bad in bad_cases:
        with pytest.raises(ContractError):
            RuntimeConfig.from_mapping(_config(metrics=[_metric(applies_to=bad)]))


# --- config ergonomics (EG-V02-5 / K5) --------------------------------------


def test_lens_judge_is_sugar_for_non_reference() -> None:
    cfg = RuntimeConfig.from_mapping(
        _config(
            metrics=[
                _metric(lens="judge", evaluator_ref="judge_score@1", required_evidence=["judge"])
            ]
        )
    )
    assert cfg.metrics[0].spec.lens.value == "non_reference"
    assert "judge" in cfg.metrics[0].spec.required_evidence


def test_bare_rubric_string_is_accepted_as_a_path() -> None:
    cfg = RuntimeConfig.from_mapping(
        _config(
            metrics=[
                _metric(
                    lens="non_reference",
                    evaluator_ref="judge_score@1",
                    required_evidence=["judge"],
                    rubric="rubrics/r.md",
                )
            ]
        )
    )
    assert cfg.metrics[0].rubric is not None
    assert cfg.metrics[0].rubric.path == "rubrics/r.md"
