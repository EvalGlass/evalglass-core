"""Slice 12 (VG-P2-3): skill wrapper + runbook smoke.

The skill is thin: SKILL.md and runbook.md document usage and status meaning and
point at validator.result.json as the authority; the behavior lives in the CLI.
This smoke runs the shipped reference fixture end-to-end through the CLI and
checks the docs advertise the working gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.contracts import Status, ValidatorResult
from scripts.validator import main

SKILL_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "evidence_packs" / "clean.json"


def test_reference_fixture_runs_end_to_end(tmp_path: Path) -> None:
    out = tmp_path / "validator.result.json"
    rc = main(["run", "--evidence-pack", str(FIXTURE), "--json", str(out)])
    result = ValidatorResult.from_dict(json.loads(out.read_text()))
    # The reference pack is a consistent authority_verdict claim: it PASSes.
    assert result.status is Status.PASS
    assert rc == 0
    assert result.families_run == ["authority_verdict"]


def test_skill_md_documents_run_command() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "validator.py run" in text
    assert "validator.result.json" in text


def test_runbook_exists_and_covers_statuses() -> None:
    runbook = (SKILL_ROOT / "runbook.md").read_text(encoding="utf-8")
    for status in ("PASS", "PASS_WITH_WARNINGS", "BLOCKED", "FAIL"):
        assert status in runbook
