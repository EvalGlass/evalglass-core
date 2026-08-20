"""Slice 6 (VG-P1-2): contract_boundary family.

Validates authority direction over a claim's required artifacts. The
Execution Loop marks how an artifact is *used* via its inline content
(``acts_as: product|canonical``, ``authoritative: true``, ``promoted: true``);
the family compares that usage against the artifact's declared ``authority``.

- FAIL: a non-product artifact acts as product authority.
- FAIL: a generated/proposed artifact is promoted to canonical.
- FAIL: two artifacts act as the same canonical product authority.
- PASS: a non-product artifact is present but is not used as product authority.

Both the family function (directly) and the end-to-end runner path are covered.
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
from scripts.families.base import FamilyContext
from scripts.families.contract_boundary import validate
from scripts.index import EvidenceIndex
from scripts.runner import run_validation

BUCKET = {
    Authority.PRODUCT: "product",
    Authority.EGTS: "egts",
    Authority.GENERATED_OR_PROPOSED: "generated_or_proposed",
    Authority.EXTERNAL: "external_contracts",
}


def art(art_id: str, authority: Authority, content: dict | None = None) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=ArtifactKind.SCORECARD, authority=authority, content=content)


def ctx_for(artifacts: list[ArtifactRef], required: list[str]) -> FamilyContext:
    boundary: dict[str, list[str]] = {}
    for a in artifacts:
        boundary.setdefault(BUCKET[a.authority], []).append(a.id)
    claim = Claim(
        id="c1",
        text="the product authority is genuine",
        expected_families=[FamilyId.CONTRACT_BOUNDARY],
        required_artifacts=required,
    )
    pack = EvidencePack(
        checkpoint="cp", source_boundary=boundary, artifacts=artifacts, claims=[claim]
    )
    index = EvidenceIndex.build(pack)
    assert index.ok, index.blocked_on
    return FamilyContext(index=index, claim=claim)


def only(findings) -> object:
    assert len(findings) == 1
    return findings[0]


# --- specificity (PASS) -----------------------------------------------------


def test_genuine_product_authority_passes() -> None:
    f = only(validate(ctx_for([art("sc", Authority.PRODUCT, {"acts_as": "product"})], ["sc"])))
    assert f.status is Status.PASS
    assert f.family_id is FamilyId.CONTRACT_BOUNDARY


def test_non_product_artifact_not_used_as_authority_passes() -> None:
    arts = [
        art("sc", Authority.PRODUCT, {"acts_as": "product"}),
        art(
            "gen", Authority.GENERATED_OR_PROPOSED, {"role": "scaffold"}
        ),  # present, not authoritative
    ]
    f = only(validate(ctx_for(arts, ["sc", "gen"])))
    assert f.status is Status.PASS


# --- sensitivity (FAIL) -----------------------------------------------------


def test_non_product_acting_as_product_authority_fails() -> None:
    arts = [art("egts-out", Authority.EGTS, {"acts_as": "product"})]
    f = only(validate(ctx_for(arts, ["egts-out"])))
    assert f.status is Status.FAIL
    assert "egts-out" in f.evidence_refs


def test_generated_artifact_promoted_to_canonical_fails() -> None:
    arts = [art("gen", Authority.GENERATED_OR_PROPOSED, {"promoted": True})]
    f = only(validate(ctx_for(arts, ["gen"])))
    assert f.status is Status.FAIL
    assert "gen" in f.evidence_refs


def test_duplicate_canonical_product_authority_fails() -> None:
    arts = [
        art("sc1", Authority.PRODUCT, {"acts_as": "product"}),
        art("sc2", Authority.PRODUCT, {"acts_as": "product"}),
    ]
    f = only(validate(ctx_for(arts, ["sc1", "sc2"])))
    assert f.status is Status.FAIL


def test_duplicate_reference_to_one_artifact_passes() -> None:
    # The claim names the same artifact twice; that is one source of truth, not two.
    arts = [art("sc", Authority.PRODUCT, {"acts_as": "product"})]
    f = only(validate(ctx_for(arts, ["sc", "sc"])))
    assert f.status is Status.PASS


def test_no_required_artifacts_blocks() -> None:
    # A contract_boundary claim with nothing to inspect must not pass.
    arts = [art("sc", Authority.PRODUCT, {"acts_as": "product"})]
    f = only(validate(ctx_for(arts, [])))  # boundary non-empty, but claim requires nothing
    assert f.status is Status.BLOCKED


# --- end to end through the runner ------------------------------------------


def test_runner_routes_and_fails_on_boundary_violation() -> None:
    arts = [art("egts-out", Authority.EGTS, {"acts_as": "product"})]
    claim = Claim(
        id="c1",
        text="product authority is genuine",
        expected_families=[FamilyId.CONTRACT_BOUNDARY],
        required_artifacts=["egts-out"],
    )
    pack = EvidencePack(
        checkpoint="cp",
        source_boundary={"egts": ["egts-out"]},
        artifacts=arts,
        claims=[claim],
    )
    result = run_validation(pack)
    assert result.status is Status.FAIL
    assert result.families_run == ["contract_boundary"]
