"""Slice 11 (VG-P2-2): Scan Gate / Code Review outputs as evidence.

The adapter materializes pack-level scan_gate_result / code_review_result as
typed artifacts (scan_gate authority / external authority) so they can prove
mechanical prerequisites — but never product verdict authority — and so a claim
that requires them BLOCKS precisely when they are absent. Validator never
reimplements scan rules or the review rubric.
"""

from __future__ import annotations

from pathlib import Path

from scripts.adapter import run_adapter
from scripts.contracts import Status


def _pack(**over) -> dict:
    base = {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-11.adjacent",
        "source_boundary": {"product": ["sc"]},
        "claims": [],
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


def test_required_scan_evidence_present_is_usable(tmp_path: Path) -> None:
    pack = _pack(
        scan_gate_result={"status": "PASS"},
        claims=[
            {
                "id": "c1",
                "text": "the verdict holds given a clean scan",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc", "scan_gate_result"],
            }
        ],
    )
    result, _ = run_adapter(pack, out_path=tmp_path / "r.json")
    # scan_gate_result was materialized and resolvable -> not blocked for absence;
    # the authority_verdict claim passes (product verdict pass, no overclaim).
    assert result.status is Status.PASS
    assert "scan_gate_result" in result.evidence_used


def test_required_scan_evidence_missing_blocks(tmp_path: Path) -> None:
    pack = _pack(
        scan_gate_result=None,  # not provided
        claims=[
            {
                "id": "c1",
                "text": "the verdict holds given a clean scan",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc", "scan_gate_result"],
            }
        ],
    )
    result, _ = run_adapter(pack, out_path=tmp_path / "r.json")
    assert result.status is Status.BLOCKED
    assert any("scan_gate_result" in b for b in result.blocked_on)


def test_required_review_evidence_missing_blocks(tmp_path: Path) -> None:
    pack = _pack(
        code_review_result=None,
        claims=[
            {
                "id": "c1",
                "text": "reviewed code supports the claim",
                "expected_families": ["contract_boundary"],
                "required_artifacts": ["code_review_result"],
            }
        ],
    )
    result, _ = run_adapter(pack, out_path=tmp_path / "r.json")
    assert result.status is Status.BLOCKED
    assert any("code_review_result" in b for b in result.blocked_on)


def test_malformed_scan_result_blocks(tmp_path: Path) -> None:
    # A non-object scan_gate_result violates the schema and must fail closed,
    # not be materialized into passing evidence.
    pack = _pack(
        scan_gate_result="PASS",  # not an object
        claims=[
            {
                "id": "c1",
                "text": "verdict holds given a clean scan",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc", "scan_gate_result"],
            }
        ],
    )
    result, _ = run_adapter(pack, out_path=tmp_path / "r.json")
    assert result.status is Status.BLOCKED


def test_scan_result_cannot_be_verdict_authority(tmp_path: Path) -> None:
    # A scan result marked as deciding the verdict must FAIL (non-product decider),
    # proving scan output cannot become verdict authority.
    pack = _pack(
        scan_gate_result={"decides_verdict": True, "claimed_status": "pass"},
        claims=[
            {
                "id": "c1",
                "text": "scan decides the verdict",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc", "scan_gate_result"],
            }
        ],
    )
    result, _ = run_adapter(pack, out_path=tmp_path / "r.json")
    assert result.status is Status.FAIL
    assert any("scan_gate_result" in f.evidence_refs for f in result.findings)
