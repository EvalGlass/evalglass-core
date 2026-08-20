"""Deterministic built-in word_count_bounds@1 (EG-V02-3 / K4).

Backs prompt-mining: a system prompt's stated length rule ("6-12 words") becomes a runnable,
domain-neutral runtime check on a named text field. Like every built-in, a non-scored state
(missing field / bad config / non-string value) is never encoded as ``0.0``.
"""

from __future__ import annotations

from typing import Any

from evalglass.core.builtins import BUILTINS, word_count_bounds
from evalglass.core.contracts import EvalUnit, EvidenceBundle, Example, UnitKind
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.registry import Direction, Lens, MetricSpec, ScoreType
from evalglass.core.scores import ScoreStatus, Validity

_UNIT = EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1")
_EVID = EvidenceBundle()


def _ctx(**params: Any) -> EvaluatorContext:
    spec = MetricSpec(
        name="word_count_bounds",
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="word_count_bounds@1",
    )
    return EvaluatorContext(spec=spec, params=params)


def _example(output: Any) -> Example:
    return Example(example_id="e1", input="in", output=output, unit=_UNIT)


def test_registered() -> None:
    assert BUILTINS["word_count_bounds@1"] is word_count_bounds.evaluate


def test_in_and_out_of_range() -> None:
    ctx = _ctx(field="title", min=1, max=5)
    good = word_count_bounds.evaluate(_example({"title": "a short clear title"}), ctx, _EVID)
    bad = word_count_bounds.evaluate(
        _example({"title": "one two three four five six seven"}), ctx, _EVID
    )
    assert (good.value, good.status) == (1.0, ScoreStatus.SCORED)
    assert (bad.value, bad.status) == (0.0, ScoreStatus.SCORED)
    assert bad.diagnostics
    assert bad.diagnostics[0].code == "word_count_bounds.out_of_bounds"


def test_boundaries_inclusive() -> None:
    ctx = _ctx(field="t", min=2, max=3)
    assert word_count_bounds.evaluate(_example({"t": "two words"}), ctx, _EVID).value == 1.0
    assert word_count_bounds.evaluate(_example({"t": "one"}), ctx, _EVID).value == 0.0


def test_one_sided_max_only() -> None:
    ctx = _ctx(field="t", max=3)
    assert word_count_bounds.evaluate(_example({"t": "a b c d"}), ctx, _EVID).value == 0.0
    assert word_count_bounds.evaluate(_example({"t": "a b"}), ctx, _EVID).value == 1.0


def test_missing_field_is_non_evaluable_not_zero() -> None:
    s = word_count_bounds.evaluate(_example({"other": "x"}), _ctx(field="t", min=1, max=5), _EVID)
    assert s.value is None
    assert s.status is ScoreStatus.NON_EVALUABLE
    assert s.validity is Validity.NOT_APPLICABLE


def test_non_string_value_is_error() -> None:
    s = word_count_bounds.evaluate(_example({"t": 42}), _ctx(field="t", min=1, max=5), _EVID)
    assert s.value is None
    assert s.status is ScoreStatus.ERROR
    assert s.validity is Validity.INVALID


def test_no_config_is_non_evaluable() -> None:
    assert word_count_bounds.evaluate(_example({"t": "a b"}), _ctx(), _EVID).status is (
        ScoreStatus.NON_EVALUABLE
    )
    # field but no bounds
    assert word_count_bounds.evaluate(_example({"t": "a b"}), _ctx(field="t"), _EVID).status is (
        ScoreStatus.NON_EVALUABLE
    )


def test_non_mapping_output_is_non_evaluable() -> None:
    s = word_count_bounds.evaluate(_example("a plain string"), _ctx(field="t", min=1, max=5), _EVID)
    assert s.status is ScoreStatus.NON_EVALUABLE


def test_empty_string_counts_as_zero_words() -> None:
    # an empty/whitespace field is 0 words -> out of a [1, _] bound (a real measured 0.0)
    ctx = _ctx(field="t", min=1, max=5)
    assert word_count_bounds.evaluate(_example({"t": "   "}), ctx, _EVID).value == 0.0
