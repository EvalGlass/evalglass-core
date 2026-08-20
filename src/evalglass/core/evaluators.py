"""The effect-free evaluator protocol (EG-M0-3b).

An evaluator is a pure function ``(example, context, evidence) -> Score | ScoreBatch``.
It receives *data* — the :class:`Example`, an :class:`EvaluatorContext` (the metric
spec under which it runs plus parameters), and the collected
:class:`EvidenceBundle` — never adapters or vendor trace shapes (``CLAUDE.md §10``).
It returns measurement results, never verdicts. Stdlib-only, effect-free.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from evalglass.core.contracts import EvidenceBundle, Example
from evalglass.core.registry import MetricSpec
from evalglass.core.scores import Score, ScoreBatch


@dataclass(frozen=True)
class EvaluatorContext:
    """What an evaluator is told about the metric it is computing."""

    spec: MetricSpec
    params: dict[str, Any] = field(default_factory=dict)


# An evaluator is any callable matching this shape. Built-ins are plain functions.
Evaluator = Callable[[Example, EvaluatorContext, EvidenceBundle], "Score | ScoreBatch"]
