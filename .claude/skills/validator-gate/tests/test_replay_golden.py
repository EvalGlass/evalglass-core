"""Slice 13 (VG-P3-3): replayable golden regression.

Archived (evidence pack -> validator.result.json) snapshots for PASS,
PASS_WITH_WARNINGS, BLOCKED, and FAIL. Replay must reproduce the result exactly
(status, families_run, claims_validated, findings, evidence_used) and be
deterministic. The result carries no timestamps or paths, so byte-equality is a
sound regression guard. To intentionally evolve a contract, regenerate the
golden *.result.json files and review the diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.adapter import run_adapter
from scripts.contracts import Status

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
CASES = ["pass", "pww", "blocked", "fail"]
EXPECTED_STATUS = {
    "pass": Status.PASS,
    "pww": Status.PASS_WITH_WARNINGS,
    "blocked": Status.BLOCKED,
    "fail": Status.FAIL,
}


def _load(name: str, suffix: str) -> dict:
    return json.loads((GOLDEN / f"{name}.{suffix}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", CASES)
def test_replay_reproduces_golden_result(name: str) -> None:
    result, _ = run_adapter(_load(name, "pack"))
    assert result.to_dict() == _load(name, "result"), f"golden drift for {name!r}"


@pytest.mark.parametrize("name", CASES)
def test_golden_expected_status(name: str) -> None:
    assert _load(name, "result")["status"] == EXPECTED_STATUS[name].value


@pytest.mark.parametrize("name", CASES)
def test_replay_is_deterministic(name: str) -> None:
    pack = _load(name, "pack")
    assert run_adapter(pack)[0].to_dict() == run_adapter(pack)[0].to_dict()


def test_pww_carries_a_warning_not_a_block() -> None:
    # The PASS_WITH_WARNINGS golden must actually carry a warning and no block.
    result = _load("pww", "result")
    assert result["warnings"]
    assert result["blocked_on"] == []
