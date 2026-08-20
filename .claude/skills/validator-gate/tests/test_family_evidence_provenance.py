"""Slice 8 (VG-P1-4): evidence_provenance family.

Validates that trust claims trace to current, typed records. Content
conventions: a baseline carries ``state`` (comparable | not_comparable |
missing_baseline | comparison_not_requested); a derived artifact carries
``derived: true`` and either inline ``provenance`` or a provenance artifact; a
run_record/baseline may carry ``timestamp``; deletion/retention claims carry
``deleted`` / ``retained`` booleans on the artifact.

- FAIL: regression claim cites a non-comparable baseline; a deletion/retention
  claim is contradicted by present evidence; a derived artifact is primary
  evidence without provenance.
- BLOCKED: no evidence; regression claim with no/missing baseline; contradictory
  timestamps.
- PASS: comparable baseline + current records; derived artifact with provenance.
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
from scripts.families.evidence_provenance import validate
from scripts.index import EvidenceIndex
from scripts.runner import run_validation


def art(
    art_id, kind=ArtifactKind.BASELINE, authority=Authority.PRODUCT, content=None
) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=kind, authority=authority, content=content)


def ctx_for(artifacts, required, surfaces=()) -> FamilyContext:
    boundary = {"product": [a.id for a in artifacts]}
    claim = Claim(
        id="c1",
        text="the regression/provenance claim is backed by records",
        expected_families=[FamilyId.EVIDENCE_PROVENANCE],
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


def test_comparable_baseline_regression_passes() -> None:
    arts = [
        art("base", content={"state": "comparable"}),
        art("run", ArtifactKind.RUN_RECORD, content={"timestamp": 100}),
    ]
    assert (
        only(validate(ctx_for(arts, ["base", "run"], surfaces=("regression",)))).status
        is Status.PASS
    )


def test_derived_artifact_with_provenance_passes() -> None:
    arts = [art("d", ArtifactKind.DIAGNOSTIC, content={"derived": True, "provenance": "run-7"})]
    assert only(validate(ctx_for(arts, ["d"]))).status is Status.PASS


def test_reproducibility_claim_without_baseline_passes() -> None:
    # Reproducibility is backed by run/provenance, not a baseline.
    arts = [art("run", ArtifactKind.RUN_RECORD, content={"timestamp": 100, "provenance": "p"})]
    assert (
        only(validate(ctx_for(arts, ["run"], surfaces=("reproducibility",)))).status is Status.PASS
    )


def test_retention_claim_consistent_passes() -> None:
    # A deletion-only surface must not fail on retained=False (wrong boolean).
    arts = [art("rec", ArtifactKind.RUN_RECORD, content={"deleted": True, "retained": False})]
    assert only(validate(ctx_for(arts, ["rec"], surfaces=("deletion",)))).status is Status.PASS


# --- sensitivity (FAIL) -----------------------------------------------------


def test_non_comparable_baseline_for_regression_fails() -> None:
    arts = [art("base", content={"state": "not_comparable"})]
    f = only(validate(ctx_for(arts, ["base"], surfaces=("regression",))))
    assert f.status is Status.FAIL
    assert "base" in f.evidence_refs


def test_derived_artifact_without_provenance_fails() -> None:
    arts = [art("d", ArtifactKind.DIAGNOSTIC, content={"derived": True})]
    f = only(validate(ctx_for(arts, ["d"])))
    assert f.status is Status.FAIL
    assert "d" in f.evidence_refs


def test_deletion_claim_contradicted_fails() -> None:
    arts = [art("rec", ArtifactKind.RUN_RECORD, content={"deleted": False})]
    f = only(validate(ctx_for(arts, ["rec"], surfaces=("deletion",))))
    assert f.status is Status.FAIL


def test_retention_claim_contradicted_fails() -> None:
    arts = [art("rec", ArtifactKind.RUN_RECORD, content={"retained": False})]
    f = only(validate(ctx_for(arts, ["rec"], surfaces=("retention",))))
    assert f.status is Status.FAIL


def test_comparison_not_requested_for_regression_blocks() -> None:
    arts = [art("base", content={"state": "comparison_not_requested"})]
    assert (
        only(validate(ctx_for(arts, ["base"], surfaces=("regression",)))).status is Status.BLOCKED
    )


# --- BLOCKED ----------------------------------------------------------------


def test_regression_claim_without_baseline_blocks() -> None:
    arts = [art("run", ArtifactKind.RUN_RECORD, content={"timestamp": 100})]
    assert only(validate(ctx_for(arts, ["run"], surfaces=("regression",)))).status is Status.BLOCKED


def test_missing_baseline_state_blocks() -> None:
    arts = [art("base", content={"state": "missing_baseline"})]
    assert (
        only(validate(ctx_for(arts, ["base"], surfaces=("regression",)))).status is Status.BLOCKED
    )


def test_contradictory_timestamps_block() -> None:
    arts = [
        art("base", content={"state": "comparable", "timestamp": 200}),
        art(
            "run", ArtifactKind.RUN_RECORD, content={"timestamp": 100}
        ),  # run older than its baseline
    ]
    assert (
        only(validate(ctx_for(arts, ["base", "run"], surfaces=("regression",)))).status
        is Status.BLOCKED
    )


def test_no_required_evidence_blocks() -> None:
    arts = [art("base", content={"state": "comparable"})]
    assert only(validate(ctx_for(arts, []))).status is Status.BLOCKED


# --- end to end -------------------------------------------------------------


def test_runner_fails_on_non_comparable_regression() -> None:
    arts = [art("base", content={"state": "not_comparable"})]
    claim = Claim(
        id="c1",
        text="scores improved over baseline",
        expected_families=[FamilyId.EVIDENCE_PROVENANCE],
        risk_surfaces=["regression"],
        required_artifacts=["base"],
    )
    pack = EvidencePack(
        checkpoint="cp", source_boundary={"product": ["base"]}, artifacts=arts, claims=[claim]
    )
    result = run_validation(pack)
    assert result.status is Status.FAIL
    assert result.families_run == ["evidence_provenance"]
