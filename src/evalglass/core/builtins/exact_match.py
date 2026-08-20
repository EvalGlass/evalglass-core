"""Built-in: exact_match (reference, binary).

1.0 when the output equals the reference, else 0.0. With no reference there is
nothing to compare against, so the result is ``non_evaluable`` — never a
misleading 0.0. Deterministic and domain-neutral.
"""

from __future__ import annotations

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "exact_match@1"


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence  # exact_match needs only the example
    name = context.spec.name
    if example.output is None:
        # No output to compare (absent or awaiting replay) — not a 0.0 quality result.
        return Score(
            metric=name,
            value=None,
            status=ScoreStatus.NON_EVALUABLE,
            validity=Validity.NOT_APPLICABLE,
            evaluator_version=VERSION,
            diagnostics=[
                Diagnostic(
                    code="exact_match.no_output",
                    severity=Severity.INFO,
                    message="no output to evaluate (absent or awaiting replay)",
                )
            ],
        )
    if example.reference is None:
        return Score(
            metric=name,
            value=None,
            status=ScoreStatus.NON_EVALUABLE,
            validity=Validity.NOT_APPLICABLE,
            evaluator_version=VERSION,
            diagnostics=[
                Diagnostic(
                    code="exact_match.no_reference",
                    severity=Severity.INFO,
                    message="no reference supplied; exact_match is reference-based",
                )
            ],
        )
    value = 1.0 if example.output == example.reference else 0.0
    return Score(
        metric=name,
        value=value,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
    )
