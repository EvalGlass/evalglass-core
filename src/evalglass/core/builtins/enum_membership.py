"""Built-in: enum_membership (non-reference, binary).

1.0 when a host-named ``field`` of a mapping output holds one of the configured ``allowed``
values, else 0.0. Deterministic and domain-neutral — the field name and allowed set are
host-supplied params, typically drafted from a structured-output schema's ``Literal[...]`` /
enum choices. Honest non-scored states (never a misleading 0.0):

* no ``field`` configured, or ``allowed`` missing / empty / not a list -> non_evaluable / N/A;
* output is not a mapping, or the field is absent                       -> non_evaluable / N/A.

A value that IS present but not in the allowed set is a genuine measured 0.0.
"""

from __future__ import annotations

from collections.abc import Mapping

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "enum_membership@1"


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
    field = context.params.get("field")
    allowed = context.params.get("allowed")

    if not isinstance(field, str) or not field:
        return _non_evaluable(
            name, "enum_membership.no_field", "no 'field' configured for this metric"
        )
    if not isinstance(allowed, list) or not allowed:
        return _non_evaluable(
            name, "enum_membership.no_allowed", "'allowed' must be a non-empty list of values"
        )
    if not isinstance(example.output, Mapping) or field not in example.output:
        return _non_evaluable(
            name, "enum_membership.field_absent", f"output has no field {field!r} to check"
        )

    value = example.output[field]
    member = value in allowed
    diagnostics = []
    if not member:
        diagnostics.append(
            Diagnostic(
                code="enum_membership.not_allowed",
                severity=Severity.WARNING,
                message=f"{field}={value!r} is not one of the allowed values",
                details={"field": field, "value": value, "allowed": list(allowed)},
            )
        )
    return Score(
        metric=name,
        value=1.0 if member else 0.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
        diagnostics=diagnostics,
    )
