"""The host command judge, wired end-to-end through ``run_config`` (ADR 0042).

Proves the config path selects the ``command`` adapter and produces a real judge score from a
host subprocess — the config-driven capability that previously forced bespoke run scripts — while
the ``fake`` adapter stays the default and an unknown/under-specified adapter is a setup error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import ContractError, ScoreStatus
from evalglass.harness.config import JudgeConfig, RuntimeConfig
from evalglass.harness.runner import run_config

_JUDGE_SCRIPT = """\
import sys, json
d = json.load(sys.stdin)
# A real host judge: score higher when it received the rubric text (proves the contract).
score = 0.9 if d.get("rubric") else 0.5
print(json.dumps({"value": score, "rationale": f"judged {d['metric']}"}))
"""


# --------------------------- config parsing ---------------------------


def test_command_adapter_parses() -> None:
    cfg = JudgeConfig.from_mapping(
        {"adapter": "command", "command": ["python", "j.py"], "timeout_seconds": 45}
    )
    assert cfg.adapter == "command"
    assert cfg.command == ("python", "j.py")
    assert cfg.timeout_seconds == 45.0


def test_fake_adapter_is_still_the_default() -> None:
    assert JudgeConfig.from_mapping({}).adapter == "fake"
    assert JudgeConfig.from_mapping({"adapter": "fake", "default_value": 0.8}).default_value == 0.8


@pytest.mark.parametrize("bad", [{"adapter": "command"}, {"adapter": "command", "command": []}])
def test_command_without_argv_is_a_setup_error(bad: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        JudgeConfig.from_mapping(bad)


def test_unknown_adapter_is_a_setup_error() -> None:
    with pytest.raises(ContractError):
        JudgeConfig.from_mapping({"adapter": "openai"})


# --------------------------- end-to-end run ---------------------------


def _judge_config(tmp_path: Path) -> RuntimeConfig:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a"}) + "\n", encoding="utf-8"
    )
    (tmp_path / "judges").mkdir()
    (tmp_path / "judges" / "j.py").write_text(_JUDGE_SCRIPT, encoding="utf-8")
    (tmp_path / "rubrics").mkdir()
    (tmp_path / "rubrics" / "f.md").write_text("score the grounded fraction\n", encoding="utf-8")
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": {
            "adapter": "command",
            "command": [sys.executable, "judges/j.py"],
            "timeout_seconds": 30,
        },
        "metrics": [
            {
                "name": "faithfulness",
                "evaluator_ref": "judge_score@1",
                "lens": "non_reference",
                "score_type": "continuous",
                "score_range": [0.0, 1.0],
                "required_evidence": ["judge"],
                "metric_status": "informational",
                "rubric": {"path": "rubrics/f.md", "version": "1"},
            }
        ],
    }
    return RuntimeConfig.from_mapping(raw)


def test_command_judge_scores_end_to_end(tmp_path: Path) -> None:
    record = run_config(_judge_config(tmp_path), tmp_path)
    score = next(s for s in record.scores if s.metric == "faithfulness")
    # The host judge ran as a subprocess, saw the rubric, and returned 0.9 → a real scored value.
    assert score.status is ScoreStatus.SCORED
    assert score.value == pytest.approx(0.9)
    # Uncalibrated → informational: a real judge changes no verdict on its own.
    assert record.scorecard.verdict.verdict.value == "informational"
