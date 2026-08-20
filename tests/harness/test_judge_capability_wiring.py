"""Judge capability is declared by the adapter and wired into authority + provenance (EG-NR-1).

The core already refuses a synthetic judge (tests/core/test_authority_capability.py); these tests
prove the *harness* reads the capability from the selected adapter and threads it through, so the
end-to-end protection is reachable and a judge's authority reflects what kind of instrument produced
its evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from evalglass.adapters.judge_fake import FakeJudgeModel
from evalglass.adapters.judge_live import LiveJudgeModel
from evalglass.adapters.judge_openai import OpenAICompatibleJudgeModel
from evalglass.adapters.judge_subprocess import SubprocessJudgeModel
from evalglass.core.authority import JudgeCapability
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config

_CAL = {"status": "calibrated", "approver": "alice", "rationale": "labels", "variance_runs": 5}
_THRESH = {
    "value": 0.5,
    "direction": "higher_is_better",
    "variance": 0.05,
    "approver": "alice",
    "rationale": "p95",
    "version": "1",
}


def test_adapters_declare_their_capability() -> None:
    # The fake is the only synthetic double; every real adapter is a measurement instrument.
    assert FakeJudgeModel().capability is JudgeCapability.SYNTHETIC_TEST_DOUBLE
    assert (
        SubprocessJudgeModel(command=["x"], root=Path()).capability is JudgeCapability.MEASUREMENT
    )
    assert (
        OpenAICompatibleJudgeModel(endpoint="https://e", model="m").capability
        is JudgeCapability.MEASUREMENT
    )
    assert LiveJudgeModel(endpoint="https://e").capability is JudgeCapability.MEASUREMENT


def _judge_config(tmp_path: Path, *, adapter: str) -> RuntimeConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a", "reference": "a"}) + "\n",
        encoding="utf-8",
    )
    if adapter == "command":
        (tmp_path / "judges").mkdir(exist_ok=True)
        (tmp_path / "judges" / "j.py").write_text(
            "import sys, json\njson.load(sys.stdin)\nprint(json.dumps({'value': 1.0}))\n",
            encoding="utf-8",
        )
        judge: dict[str, Any] = {"adapter": "command", "command": [sys.executable, "judges/j.py"]}
    else:
        judge = {"adapter": "fake", "default_value": 1.0}
    (tmp_path / "calibration").mkdir(exist_ok=True)
    (tmp_path / "calibration" / "m.json").write_text(
        json.dumps({"calibration": _CAL, "threshold": _THRESH}), encoding="utf-8"
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": judge,
        "metrics": [
            {
                "name": "m",
                "evaluator_ref": "exact_match@1",
                "lens": "reference",
                "score_type": "binary",
                "required_evidence": ["judge"],
                "metric_status": "gating",
                "calibration": "calibration/m.json",
            }
        ],
    }
    return RuntimeConfig.from_mapping(raw)


def test_fake_capability_reaches_the_scorecard_authority(tmp_path: Path) -> None:
    # The capability read from the adapter reaches authority resolution end-to-end: a fake judge,
    # even with a complete calibration record, resolves to informational with the typed reason.
    record = run_config(_judge_config(tmp_path, adapter="fake"), tmp_path)
    auth = record.scorecard.authority["m"]
    assert not auth.can_gate
    assert "judge_fake_non_authoritative" in auth.reasons


def test_swapping_the_judge_adapter_breaks_comparability(tmp_path: Path) -> None:
    # A fake and a real measurement judge are different evidence sources; the authority provenance
    # dimension must differ so a baseline comparison across the swap is not treated as comparable.
    fake = run_config(_judge_config(tmp_path / "a", adapter="fake"), tmp_path / "a")
    (tmp_path / "b").mkdir()
    measurement = run_config(_judge_config(tmp_path / "b", adapter="command"), tmp_path / "b")
    assert fake.provenance.dimensions["authority"] != measurement.provenance.dimensions["authority"]
