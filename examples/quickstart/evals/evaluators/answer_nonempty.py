"""Sample host-owned evaluator for the EvalGlass quickstart.

Scores 1.0 when the output object carries a non-empty ``answer`` field, else 0.0. This is the
shape every host evaluator follows: a deterministic, effect-free
``(example, context, evidence) -> Score``. Copy this file, change the logic for your domain,
and point a metric's ``evaluator_ref`` at ``evaluators/<file>.py:evaluate``.
"""

from __future__ import annotations

from collections.abc import Mapping

from evalglass.core import EvaluatorContext, EvidenceBundle, Example, Score, ScoreStatus, Validity


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence  # this evaluator needs only the example
    output = example.output
    answered = isinstance(output, Mapping) and bool(output.get("answer"))
    return Score(
        metric=context.spec.name,
        value=1.0 if answered else 0.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="answer_nonempty@1",
    )
