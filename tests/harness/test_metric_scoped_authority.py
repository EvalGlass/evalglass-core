"""Resolve each metric's authority from the evidence it actually consumes (Epic D / D2).

A bound metric's authority reflects only its bound sources: an unrelated proposed/forbidden source
cannot dilute it, and a proposed/forbidden source it *does* consume constrains it. An unbound legacy
metric keeps the conservative run-global (worst-source) authority.
"""

from __future__ import annotations

from evalglass.core import (
    AuthorityLevel,
    DatasetStatus,
    resolve_authority,
)
from evalglass.core.authority import ResolvedAuthority
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import _metric_authority_inputs, _run_authority


def _gating_metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "correctness",
        "evaluator_ref": "exact_match@1",
        "lens": "non_reference",
        "score_type": "binary",
        "metric_status": "gating",
        "threshold_approval": "approved",
        "threshold": 1.0,
        "score_range": [0, 1],
    }
    base.update(over)
    return base


def _resolve(config: RuntimeConfig, metric_name: str) -> ResolvedAuthority:
    metric = next(m for m in config.metrics if m.spec.name == metric_name)
    return resolve_authority(_metric_authority_inputs(metric, config, []))


def test_unrelated_proposed_trace_does_not_dilute_a_bound_validated_metric() -> None:
    # Specificity: the metric consumes only the validated candidate dataset; an unrelated proposed
    # trace in the same run must not dilute it.
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [
                _gating_metric(sources=[{"name": "gold", "role": "candidate"}]),
            ],
            "datasets": [
                {
                    "path": "g.jsonl",
                    "name": "gold",
                    "status": "validated",
                    "data_policy": "permitted",
                },
            ],
            "traces": [{"path": "t.jsonl", "name": "noise", "data_policy": "permitted"}],
        }
    )
    resolved = _resolve(config, "correctness")
    assert resolved.can_gate is True
    assert resolved.level is AuthorityLevel.GATING


def test_consumed_proposed_source_constrains_the_bound_metric() -> None:
    # Sensitivity: the metric binds a proposed dataset -> dataset_proposed keeps it informational.
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [_gating_metric(sources=[{"name": "draft", "role": "candidate"}])],
            "datasets": [
                {
                    "path": "d.jsonl",
                    "name": "draft",
                    "status": "proposed",
                    "data_policy": "permitted",
                },
            ],
        }
    )
    resolved = _resolve(config, "correctness")
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


def test_consumed_forbidden_policy_blocks_the_bound_metric() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [_gating_metric(sources=[{"name": "gold", "role": "candidate"}])],
            "datasets": [
                {
                    "path": "g.jsonl",
                    "name": "gold",
                    "status": "validated",
                    "data_policy": "forbidden",
                },
            ],
        }
    )
    resolved = _resolve(config, "correctness")
    assert resolved.blocked is True
    assert any(r.startswith("policy_") for r in resolved.reasons)


def test_bound_reference_source_status_constrains_the_metric() -> None:
    # A bound reference source that is proposed constrains the metric even when the candidate is
    # validated (D2 AC4 — every consumed source counts).
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [
                _gating_metric(
                    lens="reference",
                    sources=[
                        {"name": "gold", "role": "candidate"},
                        {"name": "silver", "role": "reference"},
                    ],
                )
            ],
            "datasets": [
                {
                    "path": "g.jsonl",
                    "name": "gold",
                    "status": "validated",
                    "data_policy": "permitted",
                },
                {
                    "path": "s.jsonl",
                    "name": "silver",
                    "status": "proposed",
                    "data_policy": "permitted",
                },
            ],
        }
    )
    resolved = _resolve(config, "correctness")
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


def test_bound_trace_source_is_never_validated_gold() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [_gating_metric(sources=[{"name": "prod", "role": "candidate"}])],
            "traces": [{"path": "t.jsonl", "name": "prod", "data_policy": "permitted"}],
        }
    )
    resolved = _resolve(config, "correctness")
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


def test_unbound_metric_keeps_run_global_worst() -> None:
    # A legacy unbound gating metric is diluted by an unrelated proposed trace (pre-D2 behavior).
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [_gating_metric()],
            "datasets": [
                {
                    "path": "g.jsonl",
                    "name": "gold",
                    "status": "validated",
                    "data_policy": "permitted",
                },
            ],
            "traces": [{"path": "t.jsonl", "name": "noise", "data_policy": "permitted"}],
        }
    )
    metric = config.metrics[0]
    resolved = resolve_authority(_metric_authority_inputs(metric, config, []))
    assert resolved.can_gate is False  # the unrelated proposed trace dilutes it (legacy worst)
    assert "dataset_proposed" in resolved.reasons
    # And the global helper agrees.
    status, _policy = _run_authority(config, [])
    assert status is DatasetStatus.PROPOSED


def test_two_metrics_resolve_independently_in_one_run() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "metrics": [
                _gating_metric(
                    name="bound_validated", sources=[{"name": "gold", "role": "candidate"}]
                ),
                _gating_metric(
                    name="bound_draft", sources=[{"name": "draft", "role": "candidate"}]
                ),
            ],
            "datasets": [
                {
                    "path": "g.jsonl",
                    "name": "gold",
                    "status": "validated",
                    "data_policy": "permitted",
                },
                {
                    "path": "d.jsonl",
                    "name": "draft",
                    "status": "proposed",
                    "data_policy": "permitted",
                },
            ],
        }
    )
    assert _resolve(config, "bound_validated").can_gate is True
    assert _resolve(config, "bound_draft").can_gate is False
