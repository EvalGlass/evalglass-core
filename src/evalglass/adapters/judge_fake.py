"""FakeJudgeModel — a deterministic, no-network judge adapter (EG-M4-1b).

The required tier never calls a live model: a judge call is an *effect* (CLAUDE.md §14), so
this adapter produces controlled judge evidence with no network and no provider SDK, driven
by a per-example directive in the example's context (``context["judge"]``) so a fixture fully
controls success, value, and every failure mode. It records a **call ledger** — the
``(example_id, metric)`` pairs it was asked to judge — so EGTS can prove the judge ran only
where data policy permitted. Every failure returns a typed ``Diagnostic`` and no value.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from evalglass.core import Diagnostic, JudgeEvidenceStatus, Severity
from evalglass.core.authority import JudgeCapability
from evalglass.harness.ports import JudgeRequest, JudgeResult

_CONTEXT_KEY = "judge"


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message)


class FakeJudgeModel:
    """A :class:`~evalglass.harness.ports.JudgeModel` that returns controlled evidence."""

    #: A deterministic test double — structurally non-authoritative (EG-NR-1). It can never gate,
    #: no matter what calibration/threshold/dataset surrounds it; the harness threads this into
    #: authority resolution so approval can never turn a synthetic double into a measurement.
    capability = JudgeCapability.SYNTHETIC_TEST_DOUBLE

    def __init__(
        self, *, default_value: float | None = None, context_key: str = _CONTEXT_KEY
    ) -> None:
        self._default_value = default_value
        self._context_key = context_key
        self.ledger: list[tuple[str, str]] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.ledger.append((request.example_id, request.metric))
        raw_directive = request.context.get(self._context_key)
        directive: Mapping[str, Any] = raw_directive if isinstance(raw_directive, Mapping) else {}
        mode = str(directive.get("mode", "ok"))
        return self._dispatch(request, mode, directive)

    def _dispatch(
        self, request: JudgeRequest, mode: str, directive: Mapping[str, Any]
    ) -> JudgeResult:
        if mode == "ok":
            return self._ok(request, directive)
        if mode == "timeout":
            return self._fail(
                request, JudgeEvidenceStatus.TIMEOUT, "judge_timeout", "judge timed out"
            )
        if mode == "provider_error":
            return self._fail(
                request,
                JudgeEvidenceStatus.PROVIDER_ERROR,
                "judge_provider_error",
                "judge provider returned an error",
            )
        if mode == "missing":
            return self._fail(
                request,
                JudgeEvidenceStatus.MISSING,
                "judge_missing_response",
                "judge returned nothing",
            )
        if mode == "malformed":
            return JudgeResult(
                example_id=request.example_id,
                metric=request.metric,
                status=JudgeEvidenceStatus.MALFORMED,
                raw_response=str(directive.get("raw", "not json")),
                diagnostics=[_diag("judge_malformed_response", "judge response was not parseable")],
            )
        # Unknown mode: fail closed rather than fabricating a score.
        return self._fail(
            request,
            JudgeEvidenceStatus.PROVIDER_ERROR,
            "judge_unknown_mode",
            f"unknown fake judge mode {mode!r}",
        )

    def _ok(self, request: JudgeRequest, directive: Mapping[str, Any]) -> JudgeResult:
        value = directive.get("value", self._default_value)
        if value is None:
            return self._fail(
                request,
                JudgeEvidenceStatus.MISSING,
                "judge_missing_response",
                "judge returned no usable value",
            )
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            # A fixture-supplied non-numeric/non-finite value fails closed (like a real judge
            # returning an unparseable score), never a silent coercion or an uncaught throw.
            return self._fail(
                request,
                JudgeEvidenceStatus.MALFORMED,
                "judge_unparseable_value",
                f"judge returned a non-numeric/non-finite value {value!r}",
            )
        rationale = directive.get("rationale")
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=JudgeEvidenceStatus.OK,
            parsed_value=float(value),
            raw_response=json.dumps({"score": value, "rationale": rationale}),
            rationale=str(rationale) if rationale is not None else None,
        )

    def _fail(
        self, request: JudgeRequest, status: JudgeEvidenceStatus, code: str, message: str
    ) -> JudgeResult:
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=status,
            diagnostics=[_diag(code, message)],
        )
