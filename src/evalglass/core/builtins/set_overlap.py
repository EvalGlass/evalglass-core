"""Built-in: set_overlap (reference, continuous [0, 1]).

Jaccard overlap between the whitespace token sets of output and reference. Two
empty token sets count as a perfect match (1.0). With no reference the result is
``non_evaluable``. Deterministic and domain-neutral.
"""

from __future__ import annotations

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "set_overlap@1"


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence
    name = context.spec.name
    if example.output is None:
        # No output to compare (absent or awaiting replay) — not a fabricated overlap score.
        return Score(
            metric=name,
            value=None,
            status=ScoreStatus.NON_EVALUABLE,
            validity=Validity.NOT_APPLICABLE,
            evaluator_version=VERSION,
            diagnostics=[
                Diagnostic(
                    code="set_overlap.no_output",
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
                    code="set_overlap.no_reference",
                    severity=Severity.INFO,
                    message="no reference supplied; set_overlap is reference-based",
                )
            ],
        )
    output_tokens = set(str(example.output).split())
    reference_tokens = set(str(example.reference).split())
    union = output_tokens | reference_tokens
    value = 1.0 if not union else len(output_tokens & reference_tokens) / len(union)
    return Score(
        metric=name,
        value=value,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
    )
