"""MetricSpec + registry validation (EG-M0-3a).

The registry is where a metric's declared meaning is validated before anything is
measured (``CLAUDE.md §10``): names/versions/types/ranges/directions/aggregation
are well-formed, unknown metrics are rejected, and emitted score names (incl.
batch members) must be declared. This is the half of EG-M0-3 that defines the
metric vocabulary; the evaluator protocol + built-ins follow in 5b.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from evalglass.core.contracts import ContractError, UnitKind
from evalglass.core.registry import (
    Aggregation,
    Direction,
    Lens,
    MetricRegistry,
    MetricSpec,
    ScoreType,
)


def _spec_dict(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "exact_match",
        "version": "1",
        "lens": "reference",
        "granularity": "call",
        "score_type": "binary",
        "direction": "higher_is_better",
        "evaluator_ref": "exact_match@1",
    }
    base.update(over)
    return base


def _continuous_dict(**over: Any) -> dict[str, Any]:
    base = _spec_dict(
        name="faithfulness",
        score_type="continuous",
        score_range=[0.0, 1.0],
        evaluator_ref="judge_faithfulness@1",
        lens="non_reference",
    )
    base.update(over)
    return base


# --- round-trip + typed values ----------------------------------------------


def test_spec_round_trips() -> None:
    spec = MetricSpec.from_dict(_continuous_dict())
    assert MetricSpec.from_dict(json.loads(json.dumps(spec.to_dict()))) == spec


def test_spec_parses_typed_enums() -> None:
    spec = MetricSpec.from_dict(_continuous_dict())
    assert spec.lens is Lens.NON_REFERENCE
    assert spec.score_type is ScoreType.CONTINUOUS
    assert spec.direction is Direction.HIGHER_IS_BETTER
    assert spec.granularity is UnitKind.CALL
    assert spec.aggregation is Aggregation.MEAN  # default


def test_emits_defaults_to_metric_name() -> None:
    spec = MetricSpec.from_dict(_spec_dict())
    assert spec.emits == ["exact_match"]


# --- invalid state (fail closed) --------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["name", "version", "lens", "granularity", "score_type", "direction", "evaluator_ref"],
)
def test_spec_missing_required_fails(missing: str) -> None:
    data = _spec_dict()
    del data[missing]
    with pytest.raises(ContractError):
        MetricSpec.from_dict(data)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("lens", "vibes"),
        ("score_type", "fuzzy"),
        ("direction", "sideways"),
        ("granularity", "atom"),
    ],
)
def test_spec_unknown_enum_fails(field: str, bad: str) -> None:
    with pytest.raises(ContractError):
        MetricSpec.from_dict(_spec_dict(**{field: bad}))


def test_continuous_requires_a_range() -> None:
    data = _continuous_dict()
    del data["score_range"]
    with pytest.raises(ContractError):
        MetricSpec.from_dict(data)


@pytest.mark.parametrize("bad_range", [[1.0, 0.0], [1.0, 1.0], [0.0], [0.0, 1.0, 2.0]])
def test_invalid_range_fails(bad_range: list[float]) -> None:
    with pytest.raises(ContractError):
        MetricSpec.from_dict(_continuous_dict(score_range=bad_range))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_range_bound_fails(bad: float) -> None:
    """NaN/±inf bounds break strict JSON and make range comparisons meaningless."""
    with pytest.raises(ContractError):
        MetricSpec.from_dict(_continuous_dict(score_range=[0.0, bad]))


# --- registry ---------------------------------------------------------------


def test_register_and_get() -> None:
    reg = MetricRegistry()
    spec = MetricSpec.from_dict(_spec_dict())
    reg.register(spec)
    assert reg.get("exact_match") is spec
    assert reg.names() == ["exact_match"]


def test_get_unknown_metric_raises() -> None:
    reg = MetricRegistry()
    with pytest.raises(ContractError):
        reg.get("nonexistent")


def test_duplicate_registration_raises() -> None:
    reg = MetricRegistry()
    reg.register(MetricSpec.from_dict(_spec_dict()))
    with pytest.raises(ContractError):
        reg.register(MetricSpec.from_dict(_spec_dict()))


def test_declared_and_undeclared_score_names() -> None:
    reg = MetricRegistry()
    reg.register(MetricSpec.from_dict(_spec_dict()))
    assert reg.declares_score("exact_match") is True
    assert reg.declares_score("hallucinated_metric") is False


def test_validate_emitted_rejects_undeclared_batch_member() -> None:
    """A ScoreBatch member whose name is not declared by any spec must be rejected."""
    reg = MetricRegistry()
    reg.register(MetricSpec.from_dict(_spec_dict(emits=["exact_match", "exact_match_norm"])))
    reg.validate_emitted("exact_match_norm")  # declared -> ok
    with pytest.raises(ContractError):
        reg.validate_emitted("undeclared_score")
