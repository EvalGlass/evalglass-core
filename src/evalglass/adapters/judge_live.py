"""Optional live judge lane (EG-M4-5; ADR 0016).

An **opt-in, deletable** judge provider lane. It is NEVER imported by a required runtime
path (core / harness / required adapters): the required tier uses the fake adapter only and
stays hermetic (no network, no provider SDK). This adapter posts a judge request to a
host-configured **HTTPS** endpoint using the *standard library* — EvalGlass ships no provider
dependency, so deleting this file leaves the required suite green (the import-boundary guard
in ``tests/core_isolation`` proves it). Absent prerequisites (no endpoint) raise
:class:`MissingPrerequisite` so the lane skips cleanly rather than failing a run.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from evalglass.adapters._jsonl import _reject_constant
from evalglass.core import Diagnostic, JudgeEvidenceStatus, Severity
from evalglass.core.authority import JudgeCapability
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import JudgeRequest, JudgeResult

# ``MissingPrerequisite`` is the framework's canonical "skip, don't fail" signal (EG-M5-1; ADR
# 0017), re-exported here so existing references (``judge_live.MissingPrerequisite``) keep working
# and every lane raises one class the attach seam can catch uniformly.
__all__ = ["LiveJudgeModel", "MissingPrerequisite"]

_RESPONSE_CAP = 2000


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message)


class LiveJudgeModel:
    """A :class:`~evalglass.harness.ports.JudgeModel` calling a host HTTPS judge endpoint."""

    #: A real measurement instrument (EG-NR-1): can earn gating authority once calibrated.
    capability = JudgeCapability.MEASUREMENT

    def __init__(
        self, *, endpoint: str | None, api_key: str | None = None, timeout_s: float = 30.0
    ) -> None:
        if not endpoint:
            raise MissingPrerequisite(
                "no judge endpoint configured; the live judge lane is unavailable"
            )
        if not endpoint.startswith("https://"):
            # Refuse plaintext egress for a live judge call — fail closed to a skip.
            raise MissingPrerequisite(f"live judge endpoint must be https, got {endpoint!r}")
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout_s

    def judge(self, request: JudgeRequest) -> JudgeResult:
        body = json.dumps(
            {
                "example_id": request.example_id,
                "metric": request.metric,
                "input": request.input,
                "output": request.output,
                "reference": request.reference,
                "rubric_ref": request.rubric_ref,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        http_request = urllib.request.Request(  # noqa: S310 - https-only, host-configured endpoint
            self._endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 # nosec B310 - https-only, host-configured
                http_request, timeout=self._timeout
            ) as response:
                # Bound the read so a huge/streaming body cannot exhaust memory (only the cap
                # is retained anyway); a mid-character split decodes lossily, then fails to parse.
                raw = response.read(_RESPONSE_CAP + 1).decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return self._fail(
                request, JudgeEvidenceStatus.PROVIDER_ERROR, f"live judge failed: {exc}"
            )
        return self._parse(request, raw)

    def _parse(self, request: JudgeRequest, raw: str) -> JudgeResult:
        capped = raw[:_RESPONSE_CAP]
        try:
            # parse_constant rejects NaN/Infinity tokens, like the JSONL adapters.
            data = json.loads(raw, parse_constant=_reject_constant)
        except ValueError:
            return self._malformed(request, capped, "live judge response was not valid JSON")
        value = data.get("score") if isinstance(data, dict) else None
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            return self._malformed(
                request, capped, "live judge response had no finite numeric 'score'"
            )
        rationale = data.get("rationale") if isinstance(data, dict) else None
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=JudgeEvidenceStatus.OK,
            parsed_value=float(value),
            raw_response=capped,
            rationale=str(rationale) if rationale is not None else None,
        )

    def _malformed(self, request: JudgeRequest, raw: str, message: str) -> JudgeResult:
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=JudgeEvidenceStatus.MALFORMED,
            raw_response=raw,
            diagnostics=[_diag("judge_malformed_response", message)],
        )

    def _fail(
        self, request: JudgeRequest, status: JudgeEvidenceStatus, message: str
    ) -> JudgeResult:
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=status,
            diagnostics=[_diag("judge_live_error", message)],
        )
