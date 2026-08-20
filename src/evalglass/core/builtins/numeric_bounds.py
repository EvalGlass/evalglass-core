"""Built-in: numeric_bounds (non-reference, binary).

1.0 when a host-named numeric ``field`` of a mapping output lies within the configured
``[min, max]`` (either bound optional), else 0.0. Deterministic and domain-neutral — the field
name and bounds are host-supplied params, typically drafted from a structured-output schema's
``ge``/``le`` constraints. Honest non-scored states (never a misleading 0.0):

* no ``field`` configured, or no ``min``/``max`` configured                 -> non_evaluable / N/A;
* output is not a mapping, or the field is absent                            -> non_evaluable / N/A;
* the field is present but not a real number (a number was expected)         -> error / invalid.

A value that IS a number but falls outside the bounds is a genuine measured 0.0.
"""

from __future__ import annotations

from collections.abc import Mapping

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "numeric_bounds@1"


def _non_evaluable(name: str, code: str, message: str) -> Score:
    return Score(
        metric=name,
        value=None,
        status=ScoreStatus.NON_EVALUABLE,
        validity=Validity.NOT_APPLICABLE,
        evaluator_version=VERSION,
        diagnostics=[Diagnostic(code=code, severity=Severity.INFO, message=message)],
    )


def _is_number(value: object) -> bool:
    # bool is a subtype of int; a True/False in a numeric field is a type error, not 1/0.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence
    name = context.spec.name
    field = context.params.get("field")
    low = context.params.get("min")
    high = context.params.get("max")

    if not isinstance(field, str) or not field:
        return _non_evaluable(
            name, "numeric_bounds.no_field", "no 'field' configured for this metric"
        )
    if low is None and high is None:
        return _non_evaluable(
            name, "numeric_bounds.no_bounds", "neither 'min' nor 'max' configured; nothing to check"
        )
    if (low is not None and not _is_number(low)) or (high is not None and not _is_number(high)):
        return _non_evaluable(
            name, "numeric_bounds.bad_bounds", "'min'/'max' must be numbers when present"
        )
    if not isinstance(example.output, Mapping) or field not in example.output:
        return _non_evaluable(
            name, "numeric_bounds.field_absent", f"output has no field {field!r} to bound-check"
        )

    value = example.output[field]
    if not _is_number(value):
        return Score(
            metric=name,
            value=None,
            status=ScoreStatus.ERROR,
            validity=Validity.INVALID,
            evaluator_version=VERSION,
            diagnostics=[
                Diagnostic(
                    code="numeric_bounds.not_numeric",
                    severity=Severity.ERROR,
                    message=f"field {field!r} is {type(value).__name__}, expected a number",
                )
            ],
        )

    in_bounds = (low is None or value >= low) and (high is None or value <= high)
    diagnostics = []
    if not in_bounds:
        diagnostics.append(
            Diagnostic(
                code="numeric_bounds.out_of_bounds",
                severity=Severity.WARNING,
                message=f"{field}={value} is outside [{low}, {high}]",
                details={"field": field, "value": value, "min": low, "max": high},
            )
        )
    return Score(
        metric=name,
        value=1.0 if in_bounds else 0.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
        diagnostics=diagnostics,
    )
