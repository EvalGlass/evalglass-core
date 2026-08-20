"""Subprocess ``TaskRunner`` — host replay over JSON in/out (EG-M2-1a).

Runs the host-declared ``argv`` (``TaskConfig``) as a child process, feeding
``{"example_id", "input"}`` on stdin and expecting ``{"output": ...}`` on stdout. The command
is run with **no shell** (``shell=False``), so a host input can never be interpreted as a shell
command — the argv is the entire trust surface (ADR 0007). Every failure mode — spawn failure,
timeout, non-zero exit, malformed or absent output — becomes a typed :class:`Diagnostic` with
``output=None``: infrastructure evidence, never a score (build contract §8). Effectful by design
(it owns the subprocess); meaning stays in the core.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - subprocess is the point of this adapter; argv is host-declared
from collections.abc import Mapping
from pathlib import Path

from evalglass.adapters._jsonl import _reject_constant
from evalglass.core import Diagnostic, Severity
from evalglass.harness.config import TaskConfig
from evalglass.harness.ports import TaskRequest, TaskResult

_STDERR_CAP = 2000  # keep captured stderr bounded in diagnostics


def _diag(code: str, message: str, *, cause: str | None = None) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message, cause=cause)


class SubprocessTaskRunner:
    """A :class:`~evalglass.harness.ports.TaskRunner` that replays via a child process."""

    def __init__(self, config: TaskConfig, root: Path) -> None:
        self._config = config
        self._root = root

    def run(self, request: TaskRequest) -> TaskResult:
        payload = json.dumps({"example_id": request.example_id, "input": request.input})
        try:
            proc = subprocess.run(  # noqa: S603  # nosec B603 - host argv, shell=False, no inject
                self._config.argv,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_s,
                cwd=self._root,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._fail(
                request, "task_timeout", f"host task exceeded {self._config.timeout_s}s timeout"
            )
        except OSError as exc:
            # Command not found / not executable — an infrastructure failure, not a quality result.
            return self._fail(request, "task_spawn_failed", f"could not start host task: {exc}")

        stderr = (proc.stderr or "")[:_STDERR_CAP]
        if proc.returncode != 0:
            return self._fail(
                request,
                "task_nonzero_exit",
                f"host task exited with code {proc.returncode}",
                cause=stderr or None,
            )
        try:
            # parse_constant rejects NaN/Infinity (non-standard JSON) so a host cannot smuggle a
            # non-finite float past the contract — the same rejector the JSONL adapters use.
            parsed = json.loads(proc.stdout, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError):
            return self._fail(
                request, "task_malformed_output", "host task stdout was not valid JSON"
            )
        if not isinstance(parsed, Mapping) or "output" not in parsed:
            return self._fail(
                request,
                "task_missing_output",
                "host task JSON did not contain an 'output' field",
            )
        return TaskResult(example_id=request.example_id, output=parsed["output"], diagnostics=[])

    def _fail(
        self, request: TaskRequest, code: str, message: str, *, cause: str | None = None
    ) -> TaskResult:
        return TaskResult(
            example_id=request.example_id,
            output=None,
            diagnostics=[_diag(code, message, cause=cause)],
        )
