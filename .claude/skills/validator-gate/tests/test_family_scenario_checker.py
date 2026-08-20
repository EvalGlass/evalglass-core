"""Slice 9 (VG-P1-5): scenario_checker family.

EGTS proves behavior; it never computes product verdict meaning. Content
conventions on EGTS artifacts: a scenario carries ``authored_expectation`` and
``scenario_version``; ``derived_from_output: true`` marks a post-hoc expectation;
a checker/scenario may carry ``decides_verdict``/``acts_as: product`` to assert
it decides the run (a violation).

- FAIL: an EGTS scenario/checker is cited as product authority, or a scenario
  expectation is post-hoc (derived from product output).
- BLOCKED: no evidence; no scenario/checker present; missing authored
  expectation; missing scenario-version linkage; a required-suite claim with no
  checker evidence.
- PASS: authored, versioned scenario with EGTS output used only as test evidence.
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
from scripts.families.scenario_checker import validate
from scripts.index import EvidenceIndex
from scripts.runner import run_validation

BUCKET = {Authority.EGTS: "egts", Authority.PRODUCT: "product"}


def art(art_id, kind, authority=Authority.EGTS, content=None) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=kind, authority=authority, content=content)


def ctx_for(artifacts, required, surfaces=()) -> FamilyContext:
    boundary: dict[str, list[str]] = {}
    for a in artifacts:
        boundary.setdefault(BUCKET[a.authority], []).append(a.id)
    claim = Claim(
        id="c1",
        text="EGTS scenarios prove behavior without deciding product meaning",
        expected_families=[FamilyId.SCENARIO_CHECKER],
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


def scenario(art_id="sc", **content) -> ArtifactRef:
    base = {"authored_expectation": "exact_match", "scenario_version": "v1"}
    base.update(content)
    return art(art_id, ArtifactKind.SCENARIO, content=base)


# --- specificity (PASS) -----------------------------------------------------


def test_authored_versioned_scenario_passes() -> None:
    arts = [scenario(), art("chk", ArtifactKind.CHECKER_OUTPUT, content={"passed": True})]
    assert only(validate(ctx_for(arts, ["sc", "chk"]))).status is Status.PASS


# --- sensitivity (FAIL) -----------------------------------------------------


def test_checker_deciding_verdict_fails() -> None:
    arts = [scenario(), art("chk", ArtifactKind.CHECKER_OUTPUT, content={"decides_verdict": True})]
    f = only(validate(ctx_for(arts, ["sc", "chk"])))
    assert f.status is Status.FAIL
    assert "chk" in f.evidence_refs


def test_scenario_acting_as_product_authority_fails() -> None:
    arts = [scenario(acts_as="product")]
    assert only(validate(ctx_for(arts, ["sc"]))).status is Status.FAIL


def test_post_hoc_expectation_fails() -> None:
    arts = [scenario(derived_from_output=True)]
    f = only(validate(ctx_for(arts, ["sc"])))
    assert f.status is Status.FAIL


# --- BLOCKED ----------------------------------------------------------------


def test_missing_authored_expectation_blocks() -> None:
    arts = [
        art("sc", ArtifactKind.SCENARIO, content={"scenario_version": "v1"})
    ]  # no authored_expectation
    assert only(validate(ctx_for(arts, ["sc"]))).status is Status.BLOCKED


def test_missing_scenario_version_blocks() -> None:
    arts = [art("sc", ArtifactKind.SCENARIO, content={"authored_expectation": "x"})]  # no version
    assert only(validate(ctx_for(arts, ["sc"]))).status is Status.BLOCKED


def test_required_suite_without_checker_blocks() -> None:
    arts = [scenario()]
    assert (
        only(validate(ctx_for(arts, ["sc"], surfaces=("required_suite",)))).status is Status.BLOCKED
    )


def test_scenario_surface_without_scenario_blocks() -> None:
    # Routed for an authored-expectation surface but only a checker is present.
    arts = [art("chk", ArtifactKind.CHECKER_OUTPUT, content={"passed": True})]
    f = only(validate(ctx_for(arts, ["chk"], surfaces=("authored_expectation",))))
    assert f.status is Status.BLOCKED


def test_non_egts_scenario_evidence_fails() -> None:
    # A scenario artifact mislabeled with product authority is a boundary violation.
    arts = [
        art(
            "sc",
            ArtifactKind.SCENARIO,
            Authority.PRODUCT,
            content={"authored_expectation": "x", "scenario_version": "v1"},
        )
    ]
    assert only(validate(ctx_for(arts, ["sc"]))).status is Status.FAIL


def test_no_scenario_or_checker_evidence_blocks() -> None:
    arts = [art("sc", ArtifactKind.SCORECARD, Authority.PRODUCT, content={"verdict": "pass"})]
    assert only(validate(ctx_for(arts, ["sc"]))).status is Status.BLOCKED


def test_no_required_evidence_blocks() -> None:
    arts = [scenario()]
    assert only(validate(ctx_for(arts, []))).status is Status.BLOCKED


# --- end to end -------------------------------------------------------------


def test_runner_fails_on_checker_as_verdict() -> None:
    arts = [scenario(), art("chk", ArtifactKind.CHECKER_OUTPUT, content={"decides_verdict": True})]
    claim = Claim(
        id="c1",
        text="checker proves behavior",
        expected_families=[FamilyId.SCENARIO_CHECKER],
        required_artifacts=["sc", "chk"],
    )
    pack = EvidencePack(
        checkpoint="cp", source_boundary={"egts": ["sc", "chk"]}, artifacts=arts, claims=[claim]
    )
    result = run_validation(pack)
    assert result.status is Status.FAIL
    assert result.families_run == ["scenario_checker"]
