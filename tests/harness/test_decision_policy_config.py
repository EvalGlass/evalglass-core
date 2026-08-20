"""Config wiring for the optional decision_policy block (M7 T2, G2).

A host declares the decision rule in YAML; it reuses the metric's approved
threshold + declared direction and carries only the statistic/adequacy knobs.

See src/evalglass/harness/config.py and docs/TETA_REDESIGN.md §8.1.
"""

from __future__ import annotations

import pytest

from evalglass.core import ContractError
from evalglass.core.decision import DecisionStatistic
from evalglass.core.registry import Direction
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


def _parse(metric: dict[str, object]) -> RuntimeConfig:
    return RuntimeConfig.from_mapping({"metrics": [metric]})


def test_absent_block_leaves_policy_none() -> None:
    cfg = _parse(_metric(threshold=0.8))
    assert cfg.metrics[0].decision_policy is None


def test_block_builds_policy_from_threshold_and_direction() -> None:
    cfg = _parse(
        _metric(
            threshold=0.8,
            metric_status="gating",
            threshold_approval="approved",
            decision_policy={"min_n_effective": 30, "max_missing_fraction": 0.05},
        )
    )
    policy = cfg.metrics[0].decision_policy
    assert policy is not None
    assert policy.threshold == 0.8
    assert policy.direction is Direction.HIGHER_IS_BETTER
    assert policy.min_n_effective == 30
    assert policy.max_missing_fraction == 0.05
    # Default statistic: the conservative lower bound for higher-is-better.
    assert policy.effective_statistic() is DecisionStatistic.LOWER_CONFIDENCE_BOUND


def test_explicit_point_statistic() -> None:
    cfg = _parse(_metric(threshold=0.8, decision_policy={"decision_statistic": "point"}))
    policy = cfg.metrics[0].decision_policy
    assert policy is not None
    assert policy.effective_statistic() is DecisionStatistic.POINT


def test_policy_without_threshold_is_a_setup_error() -> None:
    with pytest.raises(ContractError):
        _parse(_metric(decision_policy={"min_n_effective": 5}))


def test_unknown_policy_key_rejected() -> None:
    with pytest.raises(ContractError):
        _parse(_metric(threshold=0.8, decision_policy={"nonsense": 1}))


def test_bad_min_n_type_rejected() -> None:
    with pytest.raises(ContractError):
        _parse(_metric(threshold=0.8, decision_policy={"min_n_effective": 1.5}))
