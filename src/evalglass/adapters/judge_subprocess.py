"""Subprocess ``JudgeModel`` — a host command judge over JSON in/out (ADR 0042).

Runs a host-declared ``argv`` (``JudgeConfig.command``) as a child process, feeding
``{example_id, metric, input, output, reference, rubric}`` on stdin and expecting
``{"value"|"score": <0..1>, "rationale": <str>}`` on stdout. This is the beta-proven way to run
a **real host judge** inside a config-driven run: the host owns the judge logic (its prompt, its
provider, its domain preflight) in ``evals/judges/<name>.py``; the framework owns the effect and
the contract. The command runs with **no shell** (``shell=False``), so host data can never be
interpreted as a shell command — the argv is the entire trust surface (as with the M2 task runner,
ADR 0007).

Every failure mode — spawn failure, timeout, non-zero exit, malformed / non-finite / missing
output — becomes non-``OK`` :class:`JudgeResult` evidence with **no value**: a failed judge is
infrastructure evidence, never a low score (build contract §6/§9). The rubric text (if the metric
declares one) is read from the host-owned, path-contained ``rubric_ref`` and passed in stdin, so a
single judge script can serve many rubrics. Data-policy egress is enforced *upstream* in
``collect_judge_evidence`` (a forbidden source is never sent here), exactly like replay.

The judge stays **uncalibrated → informational** until a host computes an agreement study; running
a real judge changes no verdict on its own.
"""

from __future__ import annotations

import json
import math
import subprocess  # nosec B404 - subprocess is the point of this adapter; argv is host-declared
from collections.abc import Mapping, Sequence
from pathlib import Path

from evalglass.adapters._jsonl import _reject_constant
from evalglass.adapters._judge_result import malformed_result, ok_result
from evalglass.core import Diagnostic, JudgeEvidenceStatus, Severity
from evalglass.core.authority import JudgeCapability
from evalglass.harness._safe_fs import assert_within_root
from evalglass.harness.governance import GovernanceError
from evalglass.harness.ports import JudgeRequest, JudgeResult

_STDERR_CAP = 2000  # keep captured stderr bounded in diagnostics


def _diag(code: str, message: str, *, cause: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message, cause=cause)


class SubprocessJudgeModel:
    """A :class:`~evalglass.harness.ports.JudgeModel` that scores via a host child process."""

    #: A real measurement instrument (EG-NR-1): can earn gating authority once calibrated.
    capability = JudgeCapability.MEASUREMENT

    def __init__(self, *, command: Sequence[str], root: Path, timeout_s: float = 120.0) -> None:
        self._command = list(command)
        self._root = root
        self._timeout = timeout_s

    def _rubric_text(self, request: JudgeRequest) -> str | None:
        """Read the host rubric for this metric, path-contained under the evals root.

        A missing rubric is tolerated (empty text); a path that escapes the root is refused
        (fail-closed) even though the config loader already validated it — defense in depth.
        """
        if not request.rubric_ref:
            return ""
        path = self._root / request.rubric_ref
        try:
            assert_within_root(self._root, path)
        except GovernanceError:
            return None  # signal an adversarial ref to the caller (hard fail)
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""  # absent/unreadable rubric -> empty, still call the judge

    def judge(self, request: JudgeRequest) -> JudgeResult:
        rubric = self._rubric_text(request)
        if rubric is None:
            return self._fail(
                request,
                JudgeEvidenceStatus.PROVIDER_ERROR,
                "judge_rubric_path_escape",
                f"rubric path escapes the evals root: {request.rubric_ref!r}",
            )
        payload = json.dumps(
            {
                "example_id": request.example_id,
                "metric": request.metric,
                "input": request.input,
                "output": request.output,
                "reference": request.reference,
                "rubric": rubric,
            },
            default=str,
        )
        try:
            proc = subprocess.run(  # noqa: S603  # nosec B603 - host argv, shell=False, no inject
                self._command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=self._root,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._fail(
                request,
                JudgeEvidenceStatus.TIMEOUT,
                "judge_timeout",
                f"host judge exceeded {self._timeout}s timeout",
            )
        except OSError as exc:
            return self._fail(
                request,
                JudgeEvidenceStatus.PROVIDER_ERROR,
                "judge_spawn_failed",
                f"could not start host judge: {exc}",
            )
        stderr = (proc.stderr or "")[:_STDERR_CAP]
        if proc.returncode != 0:
            return self._fail(
                request,
                JudgeEvidenceStatus.PROVIDER_ERROR,
                "judge_nonzero_exit",
                f"host judge exited with code {proc.returncode}",
                cause=stderr or None,
            )
        return self._parse(request, proc.stdout)

    def _parse(self, request: JudgeRequest, stdout: str) -> JudgeResult:
        raw = (stdout or "")[:_STDERR_CAP]
        try:
            data = json.loads(stdout, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError):
            return self._malformed(request, raw, "host judge stdout was not valid JSON")
        value = data.get("score") if isinstance(data, Mapping) else None
        if value is None and isinstance(data, Mapping):
            value = data.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            return self._malformed(request, raw, "host judge output had no finite numeric score")
        clamped = 0.0 if value < 0 else 1.0 if value > 1 else float(value)
        rationale = data.get("rationale") if isinstance(data, Mapping) else None
        return ok_result(request, raw, clamped, rationale)

    def _malformed(self, request: JudgeRequest, raw: str, message: str) -> JudgeResult:
        return malformed_result(request, raw, message)

    def _fail(
        self,
        request: JudgeRequest,
        status: JudgeEvidenceStatus,
        code: str,
        message: str,
        *,
        cause: str | None = None,
    ) -> JudgeResult:
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=status,
            diagnostics=[_diag(code, message, cause=cause)],
        )
