"""Deterministic, domain-neutral built-in evaluators (EG-M0-3b).

Each built-in is a pure ``evaluate(example, context, evidence) -> Score`` function
matching the :data:`evalglass.core.evaluators.Evaluator` protocol. ``BUILTINS``
is keyed by the versioned ``evaluator_ref`` (e.g. ``exact_match@1``) so a caller
can resolve ``BUILTINS[spec.evaluator_ref]`` directly, and future versions
(``exact_match@2``) are distinct keys rather than silent overrides.
"""

from __future__ import annotations

from evalglass.core.builtins import (
    enum_membership,
    exact_match,
    field_presence,
    judge_score,
    numeric_bounds,
    set_overlap,
    structural_shape,
    trajectory_shape,
    word_count_bounds,
)
from evalglass.core.evaluators import Evaluator

BUILTINS: dict[str, Evaluator] = {
    exact_match.VERSION: exact_match.evaluate,
    set_overlap.VERSION: set_overlap.evaluate,
    field_presence.VERSION: field_presence.evaluate,
    structural_shape.VERSION: structural_shape.evaluate,
    numeric_bounds.VERSION: numeric_bounds.evaluate,
    enum_membership.VERSION: enum_membership.evaluate,
    word_count_bounds.VERSION: word_count_bounds.evaluate,
    judge_score.VERSION: judge_score.evaluate,
    trajectory_shape.VERSION: trajectory_shape.evaluate,
}

__all__ = [
    "BUILTINS",
    "enum_membership",
    "exact_match",
    "field_presence",
    "judge_score",
    "numeric_bounds",
    "set_overlap",
    "structural_shape",
    "trajectory_shape",
    "word_count_bounds",
]
