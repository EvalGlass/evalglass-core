"""word_count_bounds@1 — a host-named text field's word count within [min, max] (EG-V02-3 / K4).

1.0 when the whitespace-split word count of a host-named string ``field`` of a mapping output lies
within the configured ``[min, max]`` (either bound optional), else 0.0. Deterministic and
domain-neutral — the field name and word bounds are host-supplied params, typically drafted by
prompt-mining from a system prompt's stated length rule ("6-12 words"). Honest non-scored states
(never a misleading 0.0):

* no ``field`` configured, or no ``min``/``max`` configured                 -> non_evaluable / N/A;
* output is not a mapping, or the field is absent                           -> non_evaluable / N/A;
* the field is present but not a string (text was expected)                 -> error / invalid.

A value that IS a string but whose word count falls outside the bounds is a genuine measured 0.0.
Stdlib-only, effect-free (``CLAUDE.md §8``).
"""

from __future__ import annotations

from collections.abc import Mapping

from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "word_count_bounds@1"


def _non_evaluable(name: str, code: str, message: str) -> Score:
    return Score(
        metric=name,
        value=None,
        status=ScoreStatus.NON_EVALUABLE,
        validity=Validity.NOT_APPLICABLE,
        evaluator_version=VERSION,
        diagnostics=[Diagnostic(code=code, severity=Severity.INFO, message=message)],
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _config_issue(name: str, field: object, low: object, high: object) -> Score | None:
    """Return a non_evaluable Score if the metric's config is unusable, else None."""
    if not isinstance(field, str) or not field:
        return _non_evaluable(
            name, "word_count_bounds.no_field", "no 'field' configured for this metric"
        )
    if low is None and high is None:
        return _non_evaluable(
            name,
            "word_count_bounds.no_bounds",
            "neither 'min' nor 'max' configured; nothing to check",
        )
    if (low is not None and not _is_int(low)) or (high is not None and not _is_int(high)):
        return _non_evaluable(
            name,
            "word_count_bounds.bad_bounds",
            "'min'/'max' must be whole word counts when present",
        )
    return None


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    del evidence
    name = context.spec.name
    field = context.params.get("field")
    low = context.params.get("min")
    high = context.params.get("max")
    issue = _config_issue(name, field, low, high)
    if issue is not None:
        return issue
    assert isinstance(field, str)  # narrowed by _config_issue  # noqa: S101
    if not isinstance(example.output, Mapping) or field not in example.output:
        return _non_evaluable(
            name,
            "word_count_bounds.field_absent",
            f"output has no field {field!r} to word-count",
        )
    value = example.output[field]
    if not isinstance(value, str):
        return Score(
            metric=name,
            value=None,
            status=ScoreStatus.ERROR,
            validity=Validity.INVALID,
            evaluator_version=VERSION,
            diagnostics=[
                Diagnostic(
                    code="word_count_bounds.not_text",
                    severity=Severity.ERROR,
                    message=f"field {field!r} is {type(value).__name__}, expected a string",
                )
            ],
        )
    count = len(value.split())
    within = (low is None or count >= low) and (high is None or count <= high)
    diagnostics = []
    if not within:
        bound = f"[{'' if low is None else low}, {'' if high is None else high}]"
        diagnostics.append(
            Diagnostic(
                code="word_count_bounds.out_of_bounds",
                severity=Severity.WARNING,
                message=f"{field} has {count} words, outside {bound}",
                details={"field": field, "words": count, "min": low, "max": high},
            )
        )
    return Score(
        metric=name,
        value=1.0 if within else 0.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
        diagnostics=diagnostics,
    )
