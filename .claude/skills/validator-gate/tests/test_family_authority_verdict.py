"""Slice 7 (VG-P1-3): authority_verdict family (highest-risk).

Validates one effective product verdict + honest public wording. Conventions in
inline content: a product verdict/scorecard carries ``verdict`` (or ``status``);
a public surface carries ``claimed_status``; any artifact may carry
``decides_verdict: true`` to assert it decides the run.

- FAIL: a non-product artifact decides the verdict.
- FAIL: more than one artifact claims to decide the verdict.
- FAIL: product verdict artifacts conflict.
- FAIL: a public surface claims a stronger status than the product verdict (overclaim).
- BLOCKED: no required evidence, or no product verdict present to compare against.
- PASS: one product verdict, no usurper, every public claim no stronger than it.
"""

from __future__ import annotations

from scripts.contracts import (
    ArtifactKind,
    ArtifactRef,
    Authority,
    Claim,
    EvidencePack,
    FamilyId,
    Status,
)
from scripts.families.authority_verdict import validate
from scripts.families.base import FamilyContext
from scripts.index import EvidenceIndex
from scripts.runner import run_validation

BUCKET = {
    Authority.PRODUCT: "product",
    Authority.EXTERNAL: "external_contracts",
    Authority.SCAN_GATE: "scan_gate",
    Authority.EGTS: "egts",
}


def art(art_id, authority, kind=ArtifactKind.SCORECARD, content=None) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=kind, authority=authority, content=content)


def ctx_for(artifacts, required, surfaces=()) -> FamilyContext:
    boundary: dict[str, list[str]] = {}
    for a in artifacts:
        boundary.setdefault(BUCKET[a.authority], []).append(a.id)
    claim = Claim(
        id="c1",
        text="the public status matches the product verdict",
        expected_families=[FamilyId.AUTHORITY_VERDICT],
        risk_surfaces=list(surfaces),
        required_artifacts=required,
    )
    pack = EvidencePack(
        checkpoint="cp", source_boundary=boundary, artifacts=artifacts, claims=[claim]
    )
    index = EvidenceIndex.build(pack)
    assert index.ok, index.blocked_on
    return FamilyContext(index=index, claim=claim)


def only(findings):
    assert len(findings) == 1
    return findings[0]


# --- specificity (PASS) -----------------------------------------------------


def test_consistent_pass_passes() -> None:
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "pass"}),
        art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "pass"}),
    ]
    assert only(validate(ctx_for(arts, ["sc", "rep"]))).status is Status.PASS


def test_report_underclaim_is_allowed() -> None:
    # product passed but the report only claims informational: safe, not an overclaim.
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "pass"}),
        art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "informational"}),
    ]
    assert only(validate(ctx_for(arts, ["sc", "rep"]))).status is Status.PASS


# --- sensitivity (FAIL) -----------------------------------------------------


def test_public_overclaim_fails() -> None:
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "blocked"}),
        art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "pass"}),
    ]
    f = only(validate(ctx_for(arts, ["sc", "rep"])))
    assert f.status is Status.FAIL
    assert "rep" in f.evidence_refs


def test_non_product_deciding_verdict_fails() -> None:
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "blocked"}),
        art(
            "ci",
            Authority.SCAN_GATE,
            ArtifactKind.SCAN_RESULT,
            {"decides_verdict": True, "claimed_status": "pass"},
        ),
    ]
    f = only(validate(ctx_for(arts, ["sc", "ci"])))
    assert f.status is Status.FAIL
    assert "ci" in f.evidence_refs


def test_duplicate_deciders_fail() -> None:
    arts = [
        art(
            "v1",
            Authority.PRODUCT,
            ArtifactKind.VERDICT,
            {"verdict": "pass", "decides_verdict": True},
        ),
        art(
            "v2",
            Authority.PRODUCT,
            ArtifactKind.VERDICT,
            {"verdict": "pass", "decides_verdict": True},
        ),
    ]
    assert only(validate(ctx_for(arts, ["v1", "v2"]))).status is Status.FAIL


def test_conflicting_product_verdicts_fail() -> None:
    arts = [
        art("sc1", Authority.PRODUCT, content={"verdict": "pass"}),
        art("sc2", Authority.PRODUCT, content={"verdict": "fail"}),
    ]
    assert only(validate(ctx_for(arts, ["sc1", "sc2"]))).status is Status.FAIL


# --- BLOCKED ----------------------------------------------------------------


def test_no_product_verdict_blocks() -> None:
    arts = [art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "pass"})]
    assert only(validate(ctx_for(arts, ["rep"]))).status is Status.BLOCKED


def test_no_required_evidence_blocks() -> None:
    arts = [art("sc", Authority.PRODUCT, content={"verdict": "pass"})]
    assert only(validate(ctx_for(arts, []))).status is Status.BLOCKED


def test_public_surface_claim_without_public_artifact_blocks() -> None:
    # Routed because it touches a public surface, but only a product verdict is
    # present: there is no public wording to check -> BLOCKED, not PASS.
    arts = [art("sc", Authority.PRODUCT, content={"verdict": "pass"})]
    f = only(validate(ctx_for(arts, ["sc"], surfaces=("public_report",))))
    assert f.status is Status.BLOCKED


def test_unknown_claimed_status_blocks() -> None:
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "blocked"}),
        art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "success"}),
    ]
    assert only(validate(ctx_for(arts, ["sc", "rep"]))).status is Status.BLOCKED


def test_status_comparison_is_case_insensitive() -> None:
    # Mixed case must not slip an overclaim past the rank comparison.
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "BLOCKED"}),
        art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "PASS"}),
    ]
    assert only(validate(ctx_for(arts, ["sc", "rep"]))).status is Status.FAIL


# --- end to end -------------------------------------------------------------


def test_runner_fails_on_overclaim() -> None:
    arts = [
        art("sc", Authority.PRODUCT, content={"verdict": "blocked"}),
        art("rep", Authority.EXTERNAL, ArtifactKind.REPORT, {"claimed_status": "pass"}),
    ]
    claim = Claim(
        id="c1",
        text="report matches verdict",
        expected_families=[FamilyId.AUTHORITY_VERDICT],
        required_artifacts=["sc", "rep"],
    )
    pack = EvidencePack(
        checkpoint="cp",
        source_boundary={"product": ["sc"], "external_contracts": ["rep"]},
        artifacts=arts,
        claims=[claim],
    )
    result = run_validation(pack)
    assert result.status is Status.FAIL
    assert result.families_run == ["authority_verdict"]
