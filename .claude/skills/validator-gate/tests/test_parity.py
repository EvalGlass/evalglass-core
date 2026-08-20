"""Slice 12 (VG-P2-4): parity across core, adapter, and CLI.

The same evidence pack must yield the same status, families_run, finding count,
and evidence_used whether validated via the core runner, the Execution Loop
adapter, or the CLI. Exit codes split PASS/PASS_WITH_WARNINGS from BLOCKED/FAIL;
an unreadable pack blocks.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.adapter import run_adapter
from scripts.contracts import Status, ValidatorResult
from scripts.runner import run_validation
from scripts.validator import _exit_code, main


def _pack(*, verdict: str, claimed: str, required=("sc", "rep")) -> dict:
    return {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-12.parity",
        "source_boundary": {"product": ["sc"], "external_contracts": ["rep"]},
        "claims": [
            {
                "id": "c1",
                "text": "the report matches the verdict",
                "expected_families": ["authority_verdict"],
                "required_artifacts": list(required),
            }
        ],
        "artifacts": [
            {
                "id": "sc",
                "kind": "scorecard",
                "authority": "product",
                "content": {"verdict": verdict},
            },
            {
                "id": "rep",
                "kind": "report",
                "authority": "external",
                "content": {"claimed_status": claimed},
            },
        ],
    }


def _signature(result: ValidatorResult) -> tuple:
    return (
        result.status.value,
        tuple(result.families_run),
        len(result.findings),
        tuple(result.evidence_used),
    )


def _cli_result(pack: dict, tmp_path: Path, name: str) -> ValidatorResult:
    src = tmp_path / f"{name}.pack.json"
    src.write_text(json.dumps(pack), encoding="utf-8")
    out = tmp_path / f"{name}.result.json"
    main(["run", "--evidence-pack", str(src), "--json", str(out)])
    return ValidatorResult.from_dict(json.loads(out.read_text()))


PACKS = {
    "pass": _pack(verdict="pass", claimed="pass"),
    "fail": _pack(verdict="blocked", claimed="pass"),
    "blocked": _pack(verdict="pass", claimed="pass", required=("sc", "rep", "absent")),
}


def test_core_adapter_cli_parity(tmp_path: Path) -> None:
    for name, pack in PACKS.items():
        core = _signature(run_validation(pack))
        adapter = _signature(run_adapter(pack)[0])
        cli = _signature(_cli_result(pack, tmp_path, name))
        assert core == adapter == cli, f"parity mismatch for {name}: {core} {adapter} {cli}"


def test_expected_statuses() -> None:
    assert run_validation(PACKS["pass"]).status is Status.PASS
    assert run_validation(PACKS["fail"]).status is Status.FAIL
    assert run_validation(PACKS["blocked"]).status is Status.BLOCKED


def test_cli_exit_codes(tmp_path: Path) -> None:
    def rc(pack: dict, name: str) -> int:
        src = tmp_path / f"{name}.json"
        src.write_text(json.dumps(pack), encoding="utf-8")
        return main(["run", "--evidence-pack", str(src)])

    assert rc(PACKS["pass"], "p") == 0
    assert rc(PACKS["fail"], "f") == 1
    assert rc(PACKS["blocked"], "b") == 2


def test_exit_code_helper_maps_all_statuses() -> None:
    assert _exit_code(ValidatorResult(status=Status.PASS, checkpoint="x")) == 0
    assert _exit_code(ValidatorResult(status=Status.PASS_WITH_WARNINGS, checkpoint="x")) == 0
    assert _exit_code(ValidatorResult(status=Status.FAIL, checkpoint="x")) == 1
    assert _exit_code(ValidatorResult(status=Status.BLOCKED, checkpoint="x")) == 2


def test_unreadable_pack_blocks_via_cli(tmp_path: Path) -> None:
    rc = main(
        ["run", "--evidence-pack", str(tmp_path / "nope.json"), "--json", str(tmp_path / "r.json")]
    )
    assert rc == 2
