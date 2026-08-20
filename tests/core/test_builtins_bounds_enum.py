"""Deterministic built-ins numeric_bounds@1 and enum_membership@1 (EG-MDU-2).

These back schema-mining: a structured-output schema's ``ge``/``le`` numeric constraints and
``Literal`` choices become runnable, domain-neutral runtime checks. Like every built-in, a
non-scored state (missing field / bad config / wrong type) is never encoded as ``0.0``.
"""

from __future__ import annotations

from typing import Any

from evalglass.core.builtins import BUILTINS, enum_membership, numeric_bounds
from evalglass.core.contracts import EvalUnit, EvidenceBundle, Example, UnitKind
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType
from evalglass.core.scores import ScoreStatus, Validity

_UNIT = EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1")
_EVID = EvidenceBundle()


def _ctx(name: str, **params: Any) -> EvaluatorContext:
    spec = MetricSpec(
        name=name,
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref=f"{name}@1",
    )
    return EvaluatorContext(spec=spec, params=params)


def _example(output: Any) -> Example:
    return Example(example_id="e1", input="in", output=output, unit=_UNIT)


# --- registry ---------------------------------------------------------------


def test_new_builtins_are_registered() -> None:
    assert BUILTINS["numeric_bounds@1"] is numeric_bounds.evaluate
    assert BUILTINS["enum_membership@1"] is enum_membership.evaluate


# --- numeric_bounds ---------------------------------------------------------


def test_numeric_bounds_in_and_out_of_range() -> None:
    ctx = _ctx("numeric_bounds", field="confidence", min=0.0, max=1.0)
    good = numeric_bounds.evaluate(_example({"confidence": 0.8}), ctx, _EVID)
    bad = numeric_bounds.evaluate(_example({"confidence": 1.4}), ctx, _EVID)
    assert (good.value, good.status) == (1.0, ScoreStatus.SCORED)
    assert (bad.value, bad.status) == (0.0, ScoreStatus.SCORED)
    assert bad.diagnostics
    assert bad.diagnostics[0].code == "numeric_bounds.out_of_bounds"


def test_numeric_bounds_one_sided() -> None:
    ctx = _ctx("numeric_bounds", field="lat", min=-90.0, max=90.0)
    assert numeric_bounds.evaluate(_example({"lat": -91.0}), ctx, _EVID).value == 0.0
    assert numeric_bounds.evaluate(_example({"lat": 45.0}), ctx, _EVID).value == 1.0


def test_numeric_bounds_missing_field_is_non_evaluable_not_zero() -> None:
    ctx = _ctx("numeric_bounds", field="confidence", min=0.0, max=1.0)
    s = numeric_bounds.evaluate(_example({"other": 1}), ctx, _EVID)
    assert s.value is None
    assert s.status is ScoreStatus.NON_EVALUABLE
    assert s.validity is Validity.NOT_APPLICABLE


def test_numeric_bounds_non_numeric_value_is_error() -> None:
    ctx = _ctx("numeric_bounds", field="confidence", min=0.0, max=1.0)
    s = numeric_bounds.evaluate(_example({"confidence": "high"}), ctx, _EVID)
    assert s.value is None
    assert s.status is ScoreStatus.ERROR
    assert s.validity is Validity.INVALID


def test_numeric_bounds_bool_is_not_a_number() -> None:
    # bool is an int subtype; True in a numeric field is a type error, not 1.0.
    ctx = _ctx("numeric_bounds", field="x", min=0.0, max=1.0)
    assert numeric_bounds.evaluate(_example({"x": True}), ctx, _EVID).status is ScoreStatus.ERROR


def test_numeric_bounds_no_config_is_non_evaluable() -> None:
    assert numeric_bounds.evaluate(_example({"x": 1}), _ctx("numeric_bounds"), _EVID).status is (
        ScoreStatus.NON_EVALUABLE
    )
    ctx = _ctx("numeric_bounds", field="x")  # field but no bounds
    assert numeric_bounds.evaluate(_example({"x": 1}), ctx, _EVID).status is (
        ScoreStatus.NON_EVALUABLE
    )


# --- enum_membership --------------------------------------------------------


def test_enum_membership_member_and_non_member() -> None:
    ctx = _ctx("enum_membership", field="entity_type", allowed=["person", "organization"])
    ok = enum_membership.evaluate(_example({"entity_type": "organization"}), ctx, _EVID)
    no = enum_membership.evaluate(_example({"entity_type": "place"}), ctx, _EVID)
    assert (ok.value, ok.status) == (1.0, ScoreStatus.SCORED)
    assert (no.value, no.status) == (0.0, ScoreStatus.SCORED)
    assert no.diagnostics
    assert no.diagnostics[0].code == "enum_membership.not_allowed"


def test_enum_membership_missing_field_is_non_evaluable_not_zero() -> None:
    ctx = _ctx("enum_membership", field="entity_type", allowed=["a", "b"])
    s = enum_membership.evaluate(_example({"other": "a"}), ctx, _EVID)
    assert s.value is None
    assert s.status is ScoreStatus.NON_EVALUABLE


def test_enum_membership_bad_config_is_non_evaluable() -> None:
    ctx = _ctx("enum_membership", field="x", allowed=[])  # empty allowed
    assert enum_membership.evaluate(_example({"x": "a"}), ctx, _EVID).status is (
        ScoreStatus.NON_EVALUABLE
    )
    ctx2 = _ctx("enum_membership", field="x", allowed="ab")  # not a list
    assert enum_membership.evaluate(_example({"x": "a"}), ctx2, _EVID).status is (
        ScoreStatus.NON_EVALUABLE
    )
