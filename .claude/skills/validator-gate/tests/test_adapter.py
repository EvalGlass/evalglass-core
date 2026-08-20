"""Slice 11 (VG-P2-1): Execution Loop adapter.

The adapter is convenience plumbing: load the pack, materialize adjacent-gate
evidence, invoke the runner, write one validator.result.json, and return its
path. It changes no gate selection and synthesizes no final status. It fails
closed (via the runner) when Validator is selected without a claim or with an
invalid family id.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.adapter import run_adapter
from scripts.contracts import Status, ValidatorResult


def _pack(**over) -> dict:
    base = {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-11.adapter",
        "source_boundary": {"product": ["sc"]},
        "claims": [
            {
                "id": "c1",
                "text": "report matches verdict",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc"],
            }
        ],
        "artifacts": [
            {
                "id": "sc",
                "kind": "scorecard",
                "authority": "product",
                "content": {"verdict": "pass"},
            }
        ],
    }
    base.update(over)
    return base


def test_adapter_writes_result_and_returns_path(tmp_path: Path) -> None:
    out = tmp_path / "out" / "validator.result.json"
    result, path = run_adapter(_pack(), out_path=out)
    assert isinstance(result, ValidatorResult)
    assert Path(path).exists()
    on_disk = json.loads(Path(path).read_text())
    assert on_disk["schema_version"] == "validator.result.v1"
    assert on_disk["status"] == result.status.value


def test_adapter_blocks_when_selected_without_claim(tmp_path: Path) -> None:
    result, _ = run_adapter(
        _pack(claims=[], gate_plan={"families": ["authority_verdict"]}),
        out_path=tmp_path / "r.json",
    )
    assert result.status is Status.BLOCKED


def test_adapter_blocks_on_invalid_family(tmp_path: Path) -> None:
    result, _ = run_adapter(
        _pack(gate_plan={"families": ["vibes_check"]}), out_path=tmp_path / "r.json"
    )
    assert result.status is Status.BLOCKED
    assert any("vibes_check" in b for b in result.blocked_on)


def test_adapter_blocks_on_unreadable_pack(tmp_path: Path) -> None:
    result, _ = run_adapter(str(tmp_path / "missing.json"), out_path=tmp_path / "r.json")
    assert result.status is Status.BLOCKED


def test_adapter_does_not_invent_findings_beyond_families(tmp_path: Path) -> None:
    # The adapter must not add findings of its own; families_run reflects routing.
    result, _ = run_adapter(_pack(), out_path=tmp_path / "r.json")
    assert all(f.family_id.value in {"authority_verdict"} for f in result.findings)
