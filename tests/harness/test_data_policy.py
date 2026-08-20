"""Data-policy enforcement before effects (EG-M2-4).

Replay is an egress: it sends an example's data to a host subprocess. Data policy is enforced
*before* that effect — only an explicitly ``permitted``/``redacted`` source may egress. A
``forbidden`` (or undeclared/``unknown``) source is never sent to the subprocess at all, proven
here by a host that writes a marker file if (and only if) it runs. A forbidden active gate is
also blocked by authority resolution; egress refusal is independent of gating.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evalglass.core import Verdict
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config

# Host that records it was invoked (the egress detector) and echoes the input as output.
_MARKER_ECHO = """
import sys, json, pathlib
data = json.load(sys.stdin)
pathlib.Path("CALLED").write_text("yes")
print(json.dumps({"output": data["input"]}))
"""

_GATING = {"metric_status": "gating", "threshold_approval": "approved", "threshold": 0.5}


def _cfg(tmp_path: Path, *, policy: str, gating: bool = True) -> RuntimeConfig:
    (tmp_path / "host.py").write_text(_MARKER_ECHO, encoding="utf-8")
    # output-less record → eligible for replay (egress) unless policy forbids it
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    metric: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": "d.jsonl",
    }
    if gating:
        metric.update(_GATING)
    return RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": policy}],
            "metrics": [metric],
            "task": {"argv": [sys.executable, str(tmp_path / "host.py")], "timeout_s": 10},
        }
    )


def test_forbidden_policy_no_egress_and_blocks(tmp_path: Path) -> None:
    record = run_config(_cfg(tmp_path, policy="forbidden"), tmp_path)
    assert not (tmp_path / "CALLED").exists()  # the subprocess was never invoked — no egress
    assert record.scorecard.verdict.verdict == Verdict.BLOCKED
    assert any(d.code == "replay_egress_forbidden" for d in record.scorecard.diagnostics)


def test_permitted_policy_egress_replays_and_passes(tmp_path: Path) -> None:
    record = run_config(_cfg(tmp_path, policy="permitted"), tmp_path)
    assert (tmp_path / "CALLED").exists()  # egress happened: the host ran and filled the output
    assert record.scorecard.verdict.verdict == Verdict.PASS


def test_undeclared_policy_fails_closed_no_egress(tmp_path: Path) -> None:
    # An undeclared (unknown, the default) policy must not egress — permitted/redacted is required.
    record = run_config(_cfg(tmp_path, policy="unknown"), tmp_path)
    assert not (tmp_path / "CALLED").exists()
    assert record.scorecard.verdict.verdict == Verdict.BLOCKED


def test_forbidden_no_egress_even_when_informational(tmp_path: Path) -> None:
    # Egress refusal is independent of gating: a non-gating run still must not send forbidden data.
    record = run_config(_cfg(tmp_path, policy="forbidden", gating=False), tmp_path)
    assert not (tmp_path / "CALLED").exists()
    assert record.scorecard.verdict.verdict == Verdict.INFORMATIONAL


def test_trace_per_record_policy_override_blocks_egress(tmp_path: Path) -> None:
    # The source (config) permits, but an individual trace record overrides to forbidden — the
    # per-record policy must win and block egress (fail closed), not the laxer source default.
    (tmp_path / "host.py").write_text(_MARKER_ECHO, encoding="utf-8")
    rec = {"trace_id": "t1", "behavior": {"input": "4"}, "data_policy": "forbidden"}
    (tmp_path / "t.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    cfg = RuntimeConfig.from_mapping(
        {
            "traces": [{"path": "t.jsonl", "data_policy": "permitted"}],  # source permits
            "metrics": [
                {
                    "name": "structural_shape",
                    "evaluator_ref": "structural_shape@1",
                    "lens": "non_reference",
                    "score_type": "binary",
                }
            ],
            "task": {"argv": [sys.executable, str(tmp_path / "host.py")], "timeout_s": 10},
        }
    )
    record = run_config(cfg, tmp_path)
    assert not (tmp_path / "CALLED").exists()  # per-record forbidden → no egress
    assert any(d.code == "replay_egress_forbidden" for d in record.scorecard.diagnostics)
