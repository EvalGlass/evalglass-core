"""SubprocessTaskRunner — host replay over subprocess JSON in/out (EG-M2-1a).

The runner feeds ``{"example_id", "input"}`` on stdin and expects ``{"output": ...}`` on
stdout. Every failure mode — timeout, non-zero exit, malformed/absent output, spawn failure —
becomes typed :class:`~evalglass.core.Diagnostic` evidence with ``output=None``, never a score
and never a crash (EG-M2-1 acceptance). The command is host-declared argv run with **no shell**,
so input is data, never interpreted.
"""

from __future__ import annotations

import sys
from pathlib import Path

from evalglass.adapters.task_subprocess import SubprocessTaskRunner
from evalglass.harness.config import TaskConfig
from evalglass.harness.ports import TaskRequest, TaskRunner

_ECHO = """
import sys, json
data = json.load(sys.stdin)
print(json.dumps({"output": data["input"]}))
"""

_TIMEOUT = """
import sys, json, time
json.load(sys.stdin)
time.sleep(5)
"""

_NONZERO = """
import sys, json
json.load(sys.stdin)
sys.stderr.write("boom-on-stderr\\n")
sys.exit(3)
"""

_MALFORMED = """
import sys, json
json.load(sys.stdin)
print("not json {{{")
"""

_NO_OUTPUT_KEY = """
import sys, json
json.load(sys.stdin)
print(json.dumps({"result": 1}))
"""

# Emits a non-standard JSON constant (NaN) that default json.loads would silently accept.
_NAN_OUTPUT = """
import sys, json
json.load(sys.stdin)
print('{"output": NaN}')
"""


def _runner(tmp_path: Path, body: str, *, timeout: float = 10.0) -> SubprocessTaskRunner:
    script = tmp_path / "prog.py"
    script.write_text(body, encoding="utf-8")
    return SubprocessTaskRunner(
        TaskConfig(argv=[sys.executable, str(script)], timeout_s=timeout), tmp_path
    )


def test_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(_runner(tmp_path, _ECHO), TaskRunner)


def test_echo_returns_output_no_diagnostics(tmp_path: Path) -> None:
    res = _runner(tmp_path, _ECHO).run(TaskRequest(example_id="e1", input="2+2"))
    assert res.output == "2+2"
    assert res.diagnostics == []
    assert res.example_id == "e1"


def test_input_is_data_not_shell(tmp_path: Path) -> None:
    # Shell metacharacters in the input must be passed through verbatim, never interpreted.
    payload = "; rm -rf / `echo pwned` && :(){ :|:& };:"
    res = _runner(tmp_path, _ECHO).run(TaskRequest(example_id="e1", input=payload))
    assert res.output == payload


def test_timeout_is_infra_diagnostic(tmp_path: Path) -> None:
    res = _runner(tmp_path, _TIMEOUT, timeout=0.3).run(TaskRequest(example_id="e1", input="x"))
    assert res.output is None
    assert any(d.code == "task_timeout" for d in res.diagnostics)


def test_nonzero_exit_is_infra_diagnostic_with_stderr(tmp_path: Path) -> None:
    res = _runner(tmp_path, _NONZERO).run(TaskRequest(example_id="e1", input="x"))
    assert res.output is None
    diag = next(d for d in res.diagnostics if d.code == "task_nonzero_exit")
    assert "boom-on-stderr" in (diag.cause or "")


def test_malformed_output_is_infra_diagnostic(tmp_path: Path) -> None:
    res = _runner(tmp_path, _MALFORMED).run(TaskRequest(example_id="e1", input="x"))
    assert res.output is None
    assert any(d.code == "task_malformed_output" for d in res.diagnostics)


def test_missing_output_key_is_infra_diagnostic(tmp_path: Path) -> None:
    res = _runner(tmp_path, _NO_OUTPUT_KEY).run(TaskRequest(example_id="e1", input="x"))
    assert res.output is None
    assert any(d.code == "task_missing_output" for d in res.diagnostics)


def test_nonstandard_json_constant_is_malformed(tmp_path: Path) -> None:
    # NaN/Infinity are not standard JSON; the contract requires them rejected as malformed.
    res = _runner(tmp_path, _NAN_OUTPUT).run(TaskRequest(example_id="e1", input="x"))
    assert res.output is None
    assert any(d.code == "task_malformed_output" for d in res.diagnostics)


def test_spawn_failure_is_infra_diagnostic(tmp_path: Path) -> None:
    cfg = TaskConfig(argv=[str(tmp_path / "does-not-exist")], timeout_s=5.0)
    res = SubprocessTaskRunner(cfg, tmp_path).run(TaskRequest(example_id="e1", input="x"))
    assert res.output is None
    assert any(d.code == "task_spawn_failed" for d in res.diagnostics)
