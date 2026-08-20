"""Slice 4 (VG-P0-4): result composer — the gate's single status engine.

Proves the precedence FAIL > BLOCKED > PASS_WITH_WARNINGS > PASS; that a claim
with no covering finding blocks (the gate cannot claim PASS for an unvalidated
claim); that a proven FAIL outranks missing proof; that evidence refs, families,
and risk refs are aggregated deterministically; and that the composed result is
schema-valid and JSON round-trips.
"""

from __future__ import annotations

from scripts.composer import compose
from scripts.contracts import FamilyFinding, FamilyId, Status, ValidatorResult


def finding(
    claim_id: str, status: Status, family: FamilyId = FamilyId.AUTHORITY_VERDICT, **over: object
) -> FamilyFinding:
    base: dict[str, object] = {
        "family_id": family,
        "claim_id": claim_id,
        "status": status,
        "evidence_refs": ["scorecard-1"],
        "reason": "r",
        "remediation": "fix",
    }
    base.update(over)
    return FamilyFinding(**base)  # type: ignore[arg-type]


def test_all_pass_when_every_claim_covered() -> None:
    r = compose(checkpoint="cp", claim_ids=["c1"], findings=[finding("c1", Status.PASS)])
    assert r.status is Status.PASS
    assert r.claims_validated == ["c1"]
    assert r.families_run == ["authority_verdict"]


def test_warning_only_is_pass_with_warnings() -> None:
    r = compose(
        checkpoint="cp", claim_ids=["c1"], findings=[finding("c1", Status.PASS_WITH_WARNINGS)]
    )
    assert r.status is Status.PASS_WITH_WARNINGS


def test_blocked_finding_blocks() -> None:
    r = compose(checkpoint="cp", claim_ids=["c1"], findings=[finding("c1", Status.BLOCKED)])
    assert r.status is Status.BLOCKED


def test_fail_finding_fails() -> None:
    r = compose(checkpoint="cp", claim_ids=["c1"], findings=[finding("c1", Status.FAIL)])
    assert r.status is Status.FAIL


def test_fail_outranks_blocked() -> None:
    # A proven violation must FAIL even when other proof is also missing.
    r = compose(
        checkpoint="cp",
        claim_ids=["c1", "c2"],
        findings=[finding("c1", Status.FAIL)],
        evidence_blocked_on=["c2 evidence missing"],
    )
    assert r.status is Status.FAIL
    assert "c2 evidence missing" in r.blocked_on


def test_uncovered_claim_blocks_no_false_pass() -> None:
    # A clean run with no finding for a claim cannot be PASS.
    r = compose(checkpoint="cp", claim_ids=["c1"], findings=[])
    assert r.status is Status.BLOCKED
    assert any("c1" in b and "not validated" in b.lower() for b in r.blocked_on)


def test_evidence_blocked_on_propagates() -> None:
    r = compose(
        checkpoint="cp",
        claim_ids=["c1"],
        findings=[finding("c1", Status.PASS)],
        evidence_blocked_on=["x"],
    )
    assert r.status is Status.BLOCKED
    assert "x" in r.blocked_on


def test_mixed_families_fail_and_aggregate() -> None:
    r = compose(
        checkpoint="cp",
        claim_ids=["c1", "c2"],
        findings=[
            finding("c1", Status.PASS, FamilyId.CONTRACT_BOUNDARY),
            finding("c2", Status.FAIL, FamilyId.AUTHORITY_VERDICT, evidence_refs=["report-1"]),
        ],
    )
    assert r.status is Status.FAIL
    assert r.families_run == ["authority_verdict", "contract_boundary"]  # sorted, deduped
    assert r.evidence_used == ["report-1", "scorecard-1"]  # sorted, deduped


def test_risk_references_aggregated() -> None:
    r = compose(
        checkpoint="cp",
        claim_ids=["c1"],
        findings=[finding("c1", Status.FAIL, risk_ref="report_public_surface")],
    )
    assert r.risk_references_used == ["report_public_surface"]


def test_warnings_preserved_but_do_not_hide_blocks() -> None:
    r = compose(
        checkpoint="cp",
        claim_ids=["c1"],
        findings=[finding("c1", Status.BLOCKED)],
        warnings=["a non-critical note"],
    )
    assert r.status is Status.BLOCKED
    assert "a non-critical note" in r.warnings


def test_warnings_promote_pass_to_pass_with_warnings() -> None:
    # All findings pass but a non-critical warning exists: not a clean PASS.
    r = compose(
        checkpoint="cp",
        claim_ids=["c1"],
        findings=[finding("c1", Status.PASS)],
        warnings=["an unclassified artifact note"],
    )
    assert r.status is Status.PASS_WITH_WARNINGS


def test_fail_outranks_warnings() -> None:
    r = compose(
        checkpoint="cp",
        claim_ids=["c1"],
        findings=[finding("c1", Status.FAIL)],
        warnings=["note"],
    )
    assert r.status is Status.FAIL


def test_composed_result_is_schema_valid_and_round_trips() -> None:
    r = compose(checkpoint="cp", claim_ids=["c1"], findings=[finding("c1", Status.FAIL)])
    assert ValidatorResult.from_dict(r.to_dict()) == r


def test_compose_is_deterministic() -> None:
    kw = {
        "checkpoint": "cp",
        "claim_ids": ["c2", "c1"],
        "findings": [
            finding("c1", Status.FAIL, FamilyId.CONTRACT_BOUNDARY),
            finding("c2", Status.PASS),
        ],
    }
    assert compose(**kw).to_dict() == compose(**kw).to_dict()  # type: ignore[arg-type]
