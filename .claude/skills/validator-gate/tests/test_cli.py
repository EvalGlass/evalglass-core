"""Slice 4 (VG-P0-4): `validator` CLI smoke + exit-code mapping.

The CLI is the single behavior source. This slice wires load -> index ->
compose -> emit; with no families implemented yet, a clean pack honestly blocks
(its claims are not yet validated by any family), and a structurally broken pack
blocks for boundary reasons. Exit codes: PASS/PASS_WITH_WARNINGS -> 0,
FAIL -> 1, BLOCKED -> 2. JSON is authoritative; parent dirs are created.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.contracts import Status, ValidatorResult
from scripts.validator import _exit_code, main


def _clean_pack() -> dict:
    return {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-04.cli",
        "source_boundary": {"product": ["scorecard-1"]},
        "claims": [
            {
                "id": "c1",
                "text": "the report matches the verdict",
                "required_artifacts": ["scorecard-1"],
            }
        ],
        "artifacts": [
            {
                "id": "scorecard-1",
                "kind": "scorecard",
                "authority": "product",
                "content": {"verdict": "pass"},
            }
        ],
    }


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    fp = tmp_path / name
    fp.write_text(json.dumps(data), encoding="utf-8")
    return fp


def test_exit_code_mapping() -> None:
    def r(s: Status) -> ValidatorResult:
        return ValidatorResult(status=s, checkpoint="cp")

    assert _exit_code(r(Status.PASS)) == 0
    assert _exit_code(r(Status.PASS_WITH_WARNINGS)) == 0
    assert _exit_code(r(Status.FAIL)) == 1
    assert _exit_code(r(Status.BLOCKED)) == 2


def test_run_clean_pack_blocks_without_families(tmp_path: Path) -> None:
    pack = _write(tmp_path, "clean.json", _clean_pack())
    out = tmp_path / "out" / "result.json"
    rc = main(["run", "--evidence-pack", str(pack), "--json", str(out)])
    result = json.loads(out.read_text())
    assert result["schema_version"] == "validator.result.v1"
    assert result["status"] == "BLOCKED"  # no family has validated c1 yet
    assert any("c1" in b for b in result["blocked_on"])
    assert rc == 2
    # ValidatorResult contract accepts the emitted artifact.
    assert ValidatorResult.from_dict(result).status is Status.BLOCKED


def test_run_boundary_broken_pack_blocks(tmp_path: Path) -> None:
    bad = _clean_pack()
    bad["source_boundary"] = {}  # no authority direction
    pack = _write(tmp_path, "bad.json", bad)
    out = tmp_path / "result.json"
    rc = main(["run", "--evidence-pack", str(pack), "--json", str(out)])
    result = json.loads(out.read_text())
    assert result["status"] == "BLOCKED"
    assert rc == 2


def test_run_unreadable_pack_blocks(tmp_path: Path) -> None:
    rc = main(
        ["run", "--evidence-pack", str(tmp_path / "nope.json"), "--json", str(tmp_path / "r.json")]
    )
    assert rc == 2
    result = json.loads((tmp_path / "r.json").read_text())
    assert result["status"] == "BLOCKED"


def test_run_writes_markdown_and_creates_parent_dirs(tmp_path: Path) -> None:
    pack = _write(tmp_path, "clean.json", _clean_pack())
    out_json = tmp_path / "nested" / "deep" / "r.json"
    out_md = tmp_path / "nested" / "deep" / "r.md"
    main(["run", "--evidence-pack", str(pack), "--json", str(out_json), "--markdown", str(out_md)])
    assert out_json.exists()
    assert out_md.exists()
    assert "Validator Gate" in out_md.read_text()


def test_run_markdown_without_json_is_written(tmp_path: Path) -> None:
    pack = _write(tmp_path, "clean.json", _clean_pack())
    out_md = tmp_path / "only" / "r.md"
    main(["run", "--evidence-pack", str(pack), "--markdown", str(out_md)])
    assert out_md.exists()
    assert "Validator Gate" in out_md.read_text()


def test_run_deterministic_output(tmp_path: Path) -> None:
    pack = _write(tmp_path, "clean.json", _clean_pack())
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    main(["run", "--evidence-pack", str(pack), "--json", str(a)])
    main(["run", "--evidence-pack", str(pack), "--json", str(b)])
    assert a.read_text() == b.read_text()


def test_validate_evidence_materializes_adjacent_results(tmp_path: Path) -> None:
    # A pack using only the top-level scan_gate_result must preflight OK when a
    # claim requires it (materialization is applied, matching `run`).
    pack = _clean_pack()
    pack["scan_gate_result"] = {"status": "PASS"}
    pack["claims"][0]["required_artifacts"] = ["scorecard-1", "scan_gate_result"]
    fp = _write(tmp_path, "pack.json", pack)
    assert main(["validate-evidence", "--evidence-pack", str(fp)]) == 0


def test_validate_evidence_subcommand(tmp_path: Path) -> None:
    pack = _write(tmp_path, "clean.json", _clean_pack())
    rc = main(["validate-evidence", "--evidence-pack", str(pack)])
    assert rc == 0  # structurally valid pack (boundary ok, required artifact present)
    bad = _clean_pack()
    bad["source_boundary"] = {}
    badp = _write(tmp_path, "bad.json", bad)
    assert main(["validate-evidence", "--evidence-pack", str(badp)]) == 2
