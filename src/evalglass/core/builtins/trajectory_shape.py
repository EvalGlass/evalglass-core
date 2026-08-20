"""Built-in: trajectory_shape (non-reference, continuous [0, 1]) — aggregate over richer units.

A domain-neutral *structural completeness* measure for a step/trajectory/session unit (EG-M5-5):
the fraction of the unit's declared ``members`` that produced a non-null output, read from the
aggregate Example's ``output`` (a sequence of per-member outputs built by the harness selector).

It measures only structure — no domain meaning. A call-level unit, a unit with no members, an
output that is not a sequence, or an aggregate where *no* member produced an output all yield
``non_evaluable`` (nothing to aggregate), never a misleading ``0.0``. A genuinely partial
trajectory (some members produced output) scores the honest fraction. Deterministic and effect-free.
"""

from __future__ import annotations

from evalglass.core.contracts import (
    Diagnostic,
    EvalUnit,
    EvidenceBundle,
    Example,
    Severity,
    UnitKind,
)
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "trajectory_shape@1"


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
    unit: EvalUnit = example.unit
    if unit.kind is UnitKind.CALL:
        return _non_evaluable(
            name,
            "trajectory_shape.not_aggregate",
            "metric applies to a step/trajectory/session unit, not a call",
        )
    if not unit.members:
        return _non_evaluable(
            name, "trajectory_shape.no_members", "aggregate unit declares no member sub-units"
        )
    if not isinstance(example.output, list):
        return _non_evaluable(
            name,
            "trajectory_shape.output_not_sequence",
            "aggregate output is not a sequence of per-member outputs",
        )
    produced = sum(1 for member_output in example.output if member_output is not None)
    if produced == 0:
        # No member produced an output — there is no behavior to aggregate. Reporting ``0.0``
        # here would read as "0% complete quality" when the honest state is "no evidence"; a
        # degenerate/empty trajectory must be ``non_evaluable``, never a misleading ``0.0``
        # (no-false-confidence; EG-P1-3).
        return _non_evaluable(
            name,
            "trajectory_shape.output_all_null",
            "no member produced an output to aggregate",
        )
    return Score(
        metric=name,
        value=produced / len(unit.members),
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
    )
