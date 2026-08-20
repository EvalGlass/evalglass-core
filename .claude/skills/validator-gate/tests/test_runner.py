"""Slice 5: runner pipeline (evidence -> router -> families -> composer).

Proves the runner wires the stages and fails closed: a routed family with no
implementation BLOCKS (it never silently passes a claim it did not validate);
an index-level boundary block propagates; and, with an injected fake family, the
happy path composes the family's findings into the result. The real five
families are empty in the registry until their own slices.
"""

from __future__ import annotations

from scripts.contracts import (
    ArtifactKind,
    ArtifactRef,
    Authority,
    Claim,
    EvidencePack,
    FamilyFinding,
    FamilyId,
    Status,
)
from scripts.families.base import FamilyContext
from scripts.runner import FAMILY_REGISTRY, run_validation


def claim(cid: str, *, families=(FamilyId.AUTHORITY_VERDICT,), surfaces=(), required=()) -> Claim:
    return Claim(
        id=cid,
        text=f"text {cid}",
        expected_families=list(families),
        risk_surfaces=list(surfaces),
        required_artifacts=list(required),
    )


def pack(claims, boundary=None, artifacts=None) -> EvidencePack:
    # A structurally valid base so the index does not block on its own: one
    # product artifact, declared in the boundary. Tests that want an index block
    # override `boundary`/`artifacts` or make a claim require an absent artifact.
    if boundary is None and artifacts is None:
        boundary = {"product": ["sc-1"]}
        artifacts = [
            ArtifactRef(id="sc-1", kind=ArtifactKind.SCORECARD, authority=Authority.PRODUCT)
        ]
    return EvidencePack(
        checkpoint="EG.step-05.runner",
        source_boundary=boundary or {},
        claims=claims,
        artifacts=artifacts or [],
    )


def test_registry_contains_only_known_families() -> None:
    # Families register as their slices land; every key must be a canonical
    # FamilyId (no stray registrations).
    assert set(FAMILY_REGISTRY).issubset(set(FamilyId))


def test_pinned_claim_omitting_implied_family_is_pass_with_warnings() -> None:
    # M2 finding: a claim pinned to authority_verdict that also carries a baseline
    # surface validates (PASS) but the router warns that evidence_provenance was
    # implied and skipped -> the run is PASS_WITH_WARNINGS, not a silent PASS.
    p = EvidencePack(
        checkpoint="EG.step-15.coverage",
        source_boundary={"product": ["sc"]},
        artifacts=[
            ArtifactRef(
                id="sc",
                kind=ArtifactKind.SCORECARD,
                authority=Authority.PRODUCT,
                content={"verdict": "pass"},
            )
        ],
        claims=[
            Claim(
                id="c1",
                text="verdict holds and improved over baseline",
                expected_families=[FamilyId.AUTHORITY_VERDICT],
                risk_surfaces=["verdict", "baseline"],
                required_artifacts=["sc"],
            )
        ],
    )
    result = run_validation(p)
    assert result.status is Status.PASS_WITH_WARNINGS
    assert any("evidence_provenance" in w for w in result.warnings)


def test_unimplemented_routed_family_blocks() -> None:
    # All five families are implemented now; an empty registry proves the runner
    # still fails closed (via blocked_on) when a routed family has no impl.
    result = run_validation(pack([claim("c1")]), registry={})
    assert result.status is Status.BLOCKED
    assert any("authority_verdict" in b for b in result.blocked_on)
    assert any("c1" in b for b in result.blocked_on)


def test_index_block_propagates() -> None:
    # required artifact missing -> index blocks -> runner result blocks
    result = run_validation(pack([claim("c1", required=("absent",))]))
    assert result.status is Status.BLOCKED


def test_unroutable_claim_blocks() -> None:
    result = run_validation(pack([claim("c1", families=())]))  # nothing to route from
    assert result.status is Status.BLOCKED


def test_injected_family_happy_path() -> None:
    def fake_authority(ctx: FamilyContext) -> list[FamilyFinding]:
        return [
            FamilyFinding(
                family_id=FamilyId.AUTHORITY_VERDICT,
                claim_id=ctx.claim.id,
                status=Status.PASS,
                reason="report matches verdict",
            )
        ]

    result = run_validation(
        pack([claim("c1")]), registry={FamilyId.AUTHORITY_VERDICT: fake_authority}
    )
    assert result.status is Status.PASS
    assert result.families_run == ["authority_verdict"]
    assert result.claims_validated == ["c1"]


def test_load_failure_blocks_not_crashes() -> None:
    # An unreadable path must fail closed with a ValidatorResult, not raise.
    result = run_validation("/no/such/evidence/pack.json")
    assert result.status is Status.BLOCKED
    assert any("evidence" in b.lower() for b in result.blocked_on)


def test_family_crash_blocks_not_propagates() -> None:
    def boom(ctx: FamilyContext) -> list[FamilyFinding]:
        raise RuntimeError("kaboom")

    result = run_validation(pack([claim("c1")]), registry={FamilyId.AUTHORITY_VERDICT: boom})
    assert result.status is Status.BLOCKED
    assert any("crashed" in b and "c1" in b for b in result.blocked_on)


def test_injected_family_fail_is_composed() -> None:
    def fake_fail(ctx: FamilyContext) -> list[FamilyFinding]:
        return [
            FamilyFinding(
                family_id=FamilyId.AUTHORITY_VERDICT,
                claim_id=ctx.claim.id,
                status=Status.FAIL,
                reason="report overclaims",
                evidence_refs=["report-1"],
            )
        ]

    result = run_validation(pack([claim("c1")]), registry={FamilyId.AUTHORITY_VERDICT: fake_fail})
    assert result.status is Status.FAIL
    assert "report-1" in result.evidence_used
