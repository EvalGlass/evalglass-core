"""Shared ``JudgeResult`` constructors for the judge lanes (OpenAI-compatible, host subprocess, …).

Every judge adapter maps its provider's response to the same typed evidence: an ``OK`` result with
a clamped unit-range score, or a ``MALFORMED`` result carrying no value and one diagnostic (a failed
judge is never a fabricated low score). Centralizing the two constructions keeps the lanes different
only in *transport*, not in the shape of the evidence they emit.
"""

from __future__ import annotations

from evalglass.core import Diagnostic, JudgeEvidenceStatus, Severity
from evalglass.harness.ports import JudgeRequest, JudgeResult


def ok_result(request: JudgeRequest, raw: str, clamped: float, rationale: object) -> JudgeResult:
    """``OK`` judge evidence: the clamped unit-range score plus the optional rationale."""
    return JudgeResult(
        example_id=request.example_id,
        metric=request.metric,
        status=JudgeEvidenceStatus.OK,
        parsed_value=clamped,
        raw_response=raw,
        rationale=str(rationale) if rationale is not None else None,
    )


def malformed_result(request: JudgeRequest, raw: str, message: str) -> JudgeResult:
    """``MALFORMED`` judge evidence: no value, one diagnostic — a failed judge is not a score."""
    return JudgeResult(
        example_id=request.example_id,
        metric=request.metric,
        status=JudgeEvidenceStatus.MALFORMED,
        raw_response=raw,
        diagnostics=[
            Diagnostic(code="judge_malformed_response", severity=Severity.ERROR, message=message)
        ],
    )
