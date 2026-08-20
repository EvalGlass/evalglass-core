"""Built-in: field_presence (non-reference, continuous [0, 1]).

Fraction of the configured ``required_fields`` present in a mapping output. With
no fields configured, or a non-mapping output, there is nothing meaningful to
measure, so the result is ``non_evaluable`` rather than a misleading score.
Deterministic and domain-neutral (the field names are host-supplied params).
"""

from __future__ import annotations

from collections.abc import Mapping

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "field_presence@1"


def _non_evaluable(name: str, code: str, message: str) -> Score:
    return Score(
        metric=name,
        value=None,
        status=ScoreStatus.NON_EVALUABLE,
        validity=Validity.NOT_APPLICABLE,
        evaluator_version=VERSION,
        diagnostics=[Diagnostic(code=code, severity=Severity.INFO, message=message)],
    )


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence
    name = context.spec.name
    required = context.params.get("required_fields", [])
    if not required:
        return _non_evaluable(
            name, "field_presence.no_fields", "no required_fields configured for this metric"
        )
    # Host-supplied config: a bare string is a truthy iterable that would silently
    # score characters instead of fields — reject malformed config.
    if not isinstance(required, list) or not all(isinstance(f, str) for f in required):
        return _non_evaluable(
            name,
            "field_presence.malformed_fields",
            "required_fields must be a list of field-name strings",
        )
    if not isinstance(example.output, Mapping):
        return _non_evaluable(
            name,
            "field_presence.output_not_mapping",
            "output is not a mapping; cannot check fields",
        )
    missing = [fieldname for fieldname in required if fieldname not in example.output]
    present = len(required) - len(missing)
    diagnostics = []
    if missing:
        # Name the absent fields so a partial score is as legible as a bounds/enum failure
        # (EG-V02-5 / K5): the Scorecard's failure clusters can then group "which fields".
        diagnostics.append(
            Diagnostic(
                code="field_presence.missing_fields",
                severity=Severity.WARNING,
                message=f"required field(s) absent: {', '.join(missing)}",
                details={"missing": missing},
            )
        )
    return Score(
        metric=name,
        value=present / len(required),
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
        diagnostics=diagnostics,
    )
