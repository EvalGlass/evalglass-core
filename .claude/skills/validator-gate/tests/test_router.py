"""Slice 5 (VG-P1-1): Validator Router + checkpoint matrix.

Proves the router selects the smallest correct family set: explicit
expected_families respected; inference from risk_surfaces via the checkpoint
matrix; cross-boundary escalation when one claim touches several surfaces;
gate_plan explicit families honored; and BLOCKED (routing cannot be trusted)
when a family id is invalid, a risk-catalog ref is used as a family id, a claim
cannot be routed, or there are no claims.
"""

from __future__ import annotations

import pytest

from scripts.contracts import Claim, EvidencePack, FamilyId, Status
from scripts.router import route


def pack(claims: list[Claim], gate_plan: dict | None = None) -> EvidencePack:
    return EvidencePack(checkpoint="EG.step-05.router", claims=claims, gate_plan=gate_plan or {})


def claim(cid: str, *, families=(), surfaces=(), required=()) -> Claim:
    return Claim(
        id=cid,
        text=f"text {cid}",
        expected_families=list(families),
        risk_surfaces=list(surfaces),
        required_artifacts=list(required),
    )


def families_of(result) -> dict[str, list[str]]:
    return {rf.family_id.value: sorted(rf.claim_ids) for rf in result.families}


def test_explicit_expected_families_respected() -> None:
    r = route(pack([claim("c1", families=(FamilyId.AUTHORITY_VERDICT,))]))
    assert r.status is Status.PASS
    assert families_of(r) == {"authority_verdict": ["c1"]}


# --- coverage warning: explicit pin that omits an implied family (M2 finding) ---


def test_pinned_family_omitting_implied_surface_warns() -> None:
    # Pinned to authority_verdict, but a baseline surface implies evidence_provenance.
    # Routing is unchanged (the pin wins), but the silent skip is now a warning.
    r = route(pack([claim("c1", families=(FamilyId.AUTHORITY_VERDICT,), surfaces=("baseline",))]))
    assert r.status is Status.PASS
    assert families_of(r) == {"authority_verdict": ["c1"]}  # routing unchanged
    assert any("c1" in w and "evidence_provenance" in w for w in r.warnings)


def test_pinned_family_covering_surface_no_warning() -> None:
    # The surface ("verdict") maps to the pinned family, so nothing is skipped.
    r = route(pack([claim("c1", families=(FamilyId.AUTHORITY_VERDICT,), surfaces=("verdict",))]))
    assert r.warnings == []


def test_pure_inference_no_warning() -> None:
    # No pin: inference routes to evidence_provenance; nothing omitted.
    r = route(pack([claim("c1", surfaces=("baseline",))]))
    assert "evidence_provenance" in families_of(r)
    assert r.warnings == []


def test_gate_plan_pin_omitting_implied_surface_warns() -> None:
    r = route(
        pack([claim("c1", surfaces=("baseline",))], gate_plan={"families": ["authority_verdict"]})
    )
    assert r.status is Status.PASS
    assert any("c1" in w and "evidence_provenance" in w for w in r.warnings)


def test_router_result_warnings_round_trip() -> None:
    from scripts.contracts import RouterResult

    r = route(pack([claim("c1", families=(FamilyId.AUTHORITY_VERDICT,), surfaces=("baseline",))]))
    assert RouterResult.from_dict(r.to_dict()) == r


def test_warnings_preserved_when_another_claim_blocks_routing() -> None:
    # One claim warns (pinned-incomplete); another is unroutable (blocks). The
    # coverage warning must survive the BLOCKED return.
    r = route(
        pack(
            [
                claim("c1", families=(FamilyId.AUTHORITY_VERDICT,), surfaces=("baseline",)),
                claim("c2"),  # no families, no surfaces -> unroutable
            ]
        )
    )
    assert r.status is Status.BLOCKED
    assert any("c1" in w and "evidence_provenance" in w for w in r.warnings)


@pytest.mark.parametrize(
    ("surface", "expected"),
    [
        ("verdict", "authority_verdict"),
        ("threshold", "authority_verdict"),
        ("public_report", "authority_verdict"),
        ("baseline", "evidence_provenance"),
        ("deletion", "evidence_provenance"),
        ("scenario", "scenario_checker"),
        ("required_suite", "scenario_checker"),
        ("public_api", "contract_boundary"),
        ("generated_authority", "contract_boundary"),
        ("vendoring", "integration_boundary"),
        ("integration", "integration_boundary"),
        ("rag", "integration_boundary"),
    ],
)
def test_inference_from_risk_surface(surface: str, expected: str) -> None:
    r = route(pack([claim("c1", surfaces=(surface,))]))
    assert r.status is Status.PASS, r.blocked_on
    assert expected in families_of(r)
    assert "c1" in families_of(r)[expected]


def test_cross_boundary_escalation() -> None:
    # A report that claims a baseline improvement crosses two boundaries.
    r = route(pack([claim("c1", surfaces=("public_report", "baseline"))]))
    assert r.status is Status.PASS
    assert set(families_of(r)) == {"authority_verdict", "evidence_provenance"}


def test_gate_plan_explicit_families_used_when_claim_has_none() -> None:
    r = route(pack([claim("c1")], gate_plan={"families": ["contract_boundary"]}))
    assert r.status is Status.PASS
    assert families_of(r) == {"contract_boundary": ["c1"]}


def test_invalid_family_id_in_gate_plan_blocks() -> None:
    r = route(pack([claim("c1")], gate_plan={"families": ["vibes_check"]}))
    assert r.status is Status.BLOCKED
    assert any("vibes_check" in b for b in r.blocked_on)


def test_risk_catalog_ref_as_family_id_blocks() -> None:
    # A pure risk-catalog ref must never be accepted as a family id.
    r = route(pack([claim("c1")], gate_plan={"families": ["report_public_surface"]}))
    assert r.status is Status.BLOCKED
    assert any("report_public_surface" in b and "risk" in b.lower() for b in r.blocked_on)


def test_unroutable_claim_blocks() -> None:
    r = route(pack([claim("c1")]))  # no families, no surfaces, no gate_plan
    assert r.status is Status.BLOCKED
    assert any("c1" in b for b in r.blocked_on)


def test_no_claims_blocks() -> None:
    r = route(pack([]))
    assert r.status is Status.BLOCKED


@pytest.mark.parametrize("families_value", [123, "authority_verdict", {"x": 1}])
def test_malformed_gate_plan_families_non_list_blocks(families_value: object) -> None:
    r = route(pack([claim("c1")], gate_plan={"families": families_value}))
    assert r.status is Status.BLOCKED


def test_malformed_gate_plan_families_non_string_element_blocks() -> None:
    r = route(pack([claim("c1")], gate_plan={"families": [123]}))
    assert r.status is Status.BLOCKED
    assert any("123" in b for b in r.blocked_on)


def test_required_evidence_carried_per_family() -> None:
    r = route(
        pack([claim("c1", families=(FamilyId.AUTHORITY_VERDICT,), required=("sc-1", "rep-1"))])
    )
    rf = r.families[0]
    assert sorted(rf.required_evidence) == ["rep-1", "sc-1"]
    assert rf.reason
