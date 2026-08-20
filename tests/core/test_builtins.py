"""Evaluator protocol + deterministic built-in evaluators (EG-M0-3b).

Evaluators are pure functions ``(example, context, evidence) -> Score`` that
receive data, never adapters or vendor trace shapes. The built-ins are
domain-neutral and deterministic: same input -> same Score (``CLAUDE.md §8/§10``).
Reference metrics with no reference, and structural metrics with nothing to
check, return ``non_evaluable`` — never a misleading ``0.0``.
"""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.core.builtins import (
    BUILTINS,
    exact_match,
    field_presence,
    set_overlap,
    structural_shape,
)
from evalglass.core.contracts import EvalUnit, EvidenceBundle, Example, UnitKind
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType
from evalglass.core.scores import ScoreStatus, Validity

_UNIT = EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1")
_EVID = EvidenceBundle()


def _spec(
    name: str,
    lens: Lens,
    score_type: ScoreType,
    score_range: tuple[float, float] | None,
) -> MetricSpec:
    return MetricSpec(
        name=name,
        version="1",
        lens=lens,
        granularity=UnitKind.CALL,
        score_type=score_type,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref=f"{name}@1",
        score_range=score_range,
    )


def _example(output: Any, reference: Any = None) -> Example:
    return Example(example_id="e1", input="in", output=output, reference=reference, unit=_UNIT)


def _ctx(
    name: str,
    lens: Lens,
    st: ScoreType,
    rng: tuple[float, float] | None,
    **params: Any,
) -> EvaluatorContext:
    return EvaluatorContext(spec=_spec(name, lens, st, rng), params=params)


# --- exact_match ------------------------------------------------------------


def test_exact_match_hit_and_miss() -> None:
    ctx = _ctx("exact_match", Lens.REFERENCE, ScoreType.BINARY, None)
    hit = exact_match.evaluate(_example("4", "4"), ctx, _EVID)
    miss = exact_match.evaluate(_example("5", "4"), ctx, _EVID)
    assert (hit.value, hit.status) == (1.0, ScoreStatus.SCORED)
    assert (miss.value, miss.status) == (0.0, ScoreStatus.SCORED)
    assert hit.evaluator_version == "exact_match@1"


def test_exact_match_without_reference_is_non_evaluable() -> None:
    ctx = _ctx("exact_match", Lens.REFERENCE, ScoreType.BINARY, None)
    score = exact_match.evaluate(_example("4", reference=None), ctx, _EVID)
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.validity is Validity.NOT_APPLICABLE
    assert score.value is None
    assert score.diagnostics  # carries a reason


# --- absent output (e.g. awaiting replay) is non_evaluable, never a 0.0 (EG-M2-1b) ----------


@pytest.mark.parametrize(
    ("module", "name", "lens", "st", "rng", "params"),
    [
        (exact_match, "exact_match", Lens.REFERENCE, ScoreType.BINARY, None, {}),
        (set_overlap, "set_overlap", Lens.REFERENCE, ScoreType.CONTINUOUS, (0.0, 1.0), {}),
        (structural_shape, "structural_shape", Lens.NON_REFERENCE, ScoreType.BINARY, None, {}),
        (
            field_presence,
            "field_presence",
            Lens.NON_REFERENCE,
            ScoreType.CONTINUOUS,
            (0.0, 1.0),
            {"required_fields": ["a"]},
        ),
    ],
)
def test_missing_output_is_non_evaluable_not_zero(
    module: Any, name: str, lens: Lens, st: ScoreType, rng: tuple[float, float] | None, params: Any
) -> None:
    # An output-requiring built-in must treat an absent output as non_evaluable — never a
    # fabricated 0.0 that an active gate could fail on (the false-confidence trap).
    ctx = _ctx(name, lens, st, rng, **params)
    score = module.evaluate(_example(output=None, reference="x"), ctx, _EVID)
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.value is None


# --- set_overlap ------------------------------------------------------------


def test_set_overlap_jaccard() -> None:
    ctx = _ctx("set_overlap", Lens.REFERENCE, ScoreType.CONTINUOUS, (0.0, 1.0))
    assert set_overlap.evaluate(_example("a b c", "a b c"), ctx, _EVID).value == pytest.approx(1.0)
    assert set_overlap.evaluate(_example("a b", "c d"), ctx, _EVID).value == pytest.approx(0.0)
    half = set_overlap.evaluate(_example("a b", "a c"), ctx, _EVID)  # intersection=1 union=3
    assert abs(half.value - (1 / 3)) < 1e-9  # type: ignore[operator]


def test_set_overlap_without_reference_is_non_evaluable() -> None:
    ctx = _ctx("set_overlap", Lens.REFERENCE, ScoreType.CONTINUOUS, (0.0, 1.0))
    assert set_overlap.evaluate(_example("a b"), ctx, _EVID).status is ScoreStatus.NON_EVALUABLE


# --- field_presence ---------------------------------------------------------


def test_field_presence_fraction() -> None:
    ctx = _ctx(
        "field_presence",
        Lens.NON_REFERENCE,
        ScoreType.CONTINUOUS,
        (0.0, 1.0),
        required_fields=["a", "b", "c", "d"],
    )
    score = field_presence.evaluate(_example({"a": 1, "b": 2}), ctx, _EVID)
    assert score.value == pytest.approx(0.5)
    assert score.status is ScoreStatus.SCORED
    # K5: a partial score names the absent fields so the failure is legible.
    codes = [d.code for d in score.diagnostics]
    assert "field_presence.missing_fields" in codes
    missing = next(d for d in score.diagnostics if d.code == "field_presence.missing_fields")
    assert set(missing.details["missing"]) == {"c", "d"}


def test_field_presence_full_score_has_no_missing_diagnostic() -> None:
    ctx = _ctx(
        "field_presence",
        Lens.NON_REFERENCE,
        ScoreType.CONTINUOUS,
        (0.0, 1.0),
        required_fields=["a"],
    )
    score = field_presence.evaluate(_example({"a": 1}), ctx, _EVID)
    assert score.value == 1.0
    assert not score.diagnostics


def test_field_presence_non_mapping_output_is_non_evaluable() -> None:
    ctx = _ctx(
        "field_presence",
        Lens.NON_REFERENCE,
        ScoreType.CONTINUOUS,
        (0.0, 1.0),
        required_fields=["a"],
    )
    score = field_presence.evaluate(_example("not a dict"), ctx, _EVID)
    assert score.status is ScoreStatus.NON_EVALUABLE


def test_field_presence_without_configured_fields_is_non_evaluable() -> None:
    ctx = _ctx("field_presence", Lens.NON_REFERENCE, ScoreType.CONTINUOUS, (0.0, 1.0))
    score = field_presence.evaluate(_example({"a": 1}), ctx, _EVID)
    assert score.status is ScoreStatus.NON_EVALUABLE


def test_field_presence_rejects_string_required_fields() -> None:
    """A bare string config ('status') must not be scored character-by-character."""
    ctx = _ctx(
        "field_presence",
        Lens.NON_REFERENCE,
        ScoreType.CONTINUOUS,
        (0.0, 1.0),
        required_fields="status",
    )
    score = field_presence.evaluate(_example({"status": "ok"}), ctx, _EVID)
    assert score.status is ScoreStatus.NON_EVALUABLE


# --- structural_shape -------------------------------------------------------


def test_structural_shape_binary() -> None:
    ctx = _ctx("structural_shape", Lens.NON_REFERENCE, ScoreType.BINARY, None)
    assert structural_shape.evaluate(_example({"k": "v"}), ctx, _EVID).value == pytest.approx(1.0)
    assert structural_shape.evaluate(_example("plain string"), ctx, _EVID).value == pytest.approx(
        0.0
    )


# --- protocol + determinism -------------------------------------------------


def test_builtins_registry_is_keyed_by_versioned_ref() -> None:
    # keyed by evaluator_ref so BUILTINS[spec.evaluator_ref] resolves directly
    assert set(BUILTINS) == {
        "exact_match@1",
        "set_overlap@1",
        "field_presence@1",
        "structural_shape@1",
        "numeric_bounds@1",
        "enum_membership@1",
        "word_count_bounds@1",
        "judge_score@1",
        "trajectory_shape@1",
    }


def test_builtins_are_deterministic() -> None:
    ctx = _ctx("exact_match", Lens.REFERENCE, ScoreType.BINARY, None)
    ex = _example("4", "4")
    assert exact_match.evaluate(ex, ctx, _EVID) == exact_match.evaluate(ex, ctx, _EVID)
