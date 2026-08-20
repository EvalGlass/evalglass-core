"""Replay route — missing-output examples → TaskRunner (EG-M2-1b).

A dataset may declare ``input`` (+ ``reference``) without an ``output`` — those examples are
"awaiting replay". When ``task:`` is configured, the runner replays each through the host
``TaskRunner`` and fills the output before scoring. A replayed-task **failure** is
infrastructure evidence that feeds the existing route-error/excluded path, so an active gate
**blocks** rather than passing over an example that never produced output. Only the normalized
output value reaches the evaluator (here ``exact_match`` compares it to the reference) — never
the raw subprocess result, which a leaked object would expose as a non-matching value.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evalglass.core import Verdict
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config

# Host that echoes the input as the output (the "system under eval").
_ECHO = """
import sys, json
data = json.load(sys.stdin)
print(json.dumps({"output": data["input"]}))
"""

# Host that fails — replay must not turn this into a quality score.
_FAIL = """
import sys, json
json.load(sys.stdin)
sys.exit(2)
"""

_GATING = {"metric_status": "gating", "threshold_approval": "approved", "threshold": 0.5}


def _cfg(
    tmp_path: Path,
    *,
    host_body: str,
    record: dict[str, object],
    gating: bool = True,
    with_task: bool = True,
) -> RuntimeConfig:
    (tmp_path / "host.py").write_text(host_body, encoding="utf-8")
    (tmp_path / "d.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    metric: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": "d.jsonl",
    }
    if gating:
        metric.update(_GATING)
    raw: dict[str, object] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "metrics": [metric],
    }
    if with_task:
        raw["task"] = {"argv": [sys.executable, str(tmp_path / "host.py")], "timeout_s": 10}
    return RuntimeConfig.from_mapping(raw)


def test_replay_fills_missing_output_and_gate_passes(tmp_path: Path) -> None:
    # echo replay fills output from input "4"; exact_match(output="4", reference="4") -> 1.0.
    # A PASS proves the evaluator saw a normalized scalar, not a raw subprocess object.
    record = run_config(
        _cfg(tmp_path, host_body=_ECHO, record={"input": "4", "reference": "4"}), tmp_path
    )
    assert record.scorecard.verdict.verdict == Verdict.PASS


def test_replayed_failure_blocks_active_gate(tmp_path: Path) -> None:
    record = run_config(
        _cfg(tmp_path, host_body=_FAIL, record={"input": "4", "reference": "4"}), tmp_path
    )
    # A failed replay must block an active gate — never a pass over an output-less example.
    assert record.scorecard.verdict.verdict == Verdict.BLOCKED
    assert any(d.code.startswith("task_") for d in record.scorecard.diagnostics)


def test_present_output_is_not_replayed(tmp_path: Path) -> None:
    # output already present → the (failing) host must not be invoked at all.
    record = run_config(
        _cfg(tmp_path, host_body=_FAIL, record={"input": "x", "output": "4", "reference": "4"}),
        tmp_path,
    )
    assert record.scorecard.verdict.verdict == Verdict.PASS
    assert not any(d.code.startswith("task_") for d in record.scorecard.diagnostics)


def test_no_task_config_means_no_replay(tmp_path: Path) -> None:
    # No task: → no replay → output stays missing → a non-gating run stays informational
    # (no fabricated pass, no crash).
    record = run_config(
        _cfg(
            tmp_path,
            host_body=_ECHO,
            record={"input": "4", "reference": "4"},
            gating=False,
            with_task=False,
        ),
        tmp_path,
    )
    assert record.scorecard.verdict.verdict == Verdict.INFORMATIONAL
