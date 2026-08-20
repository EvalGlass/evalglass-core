"""Built-in: structural_shape (non-reference, binary).

1.0 when the output is a well-formed structured object (a mapping), else 0.0.
A deterministic, domain-neutral structural-validity floor: if the output will not
even parse as structured data, no downstream correctness metric is meaningful
(``CLAUDE.md §9``, diagnostic order — structural validity first).
"""

from __future__ import annotations

from collections.abc import Mapping

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "structural_shape@1"


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence
    if example.output is None:
        # An absent output is "nothing to measure" — non_evaluable, not "unstructured" (0.0).
        return Score(
            metric=context.spec.name,
            value=None,
            status=ScoreStatus.NON_EVALUABLE,
            validity=Validity.NOT_APPLICABLE,
            evaluator_version=VERSION,
            diagnostics=[
                Diagnostic(
                    code="structural_shape.no_output",
                    severity=Severity.INFO,
                    message="no output to evaluate (absent or awaiting replay)",
                )
            ],
        )
    value = 1.0 if isinstance(example.output, Mapping) else 0.0
    return Score(
        metric=context.spec.name,
        value=value,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
    )
