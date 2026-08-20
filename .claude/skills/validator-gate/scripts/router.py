"""Validator Router + checkpoint matrix (VG-P1-1).

Selects the smallest necessary family set for the selected claims. For each
claim: honor explicit ``expected_families``; else a gate-plan-level explicit
family list; else infer from ``risk_surfaces`` via the checkpoint matrix.
Routing fails closed (BLOCKED — routing itself cannot be trusted) when a family
id is invalid, a risk-catalog ref is named where a family id is required, a
claim cannot be routed, or there are no claims.

Cross-boundary escalation is the natural union of each surface's family set: a
claim that touches both a report surface and a baseline surface routes to both
authority_verdict and evidence_provenance. The mapping favors the *smallest*
set — report/CI/trace surfaces route to authority_verdict (verdict overclaim),
and provenance/baseline surfaces add evidence_provenance only when present.
"""

from __future__ import annotations

from typing import Any

from scripts.contracts import Claim, EvidencePack, FamilyId, RouterFamily, RouterResult, Status
from scripts.risk_catalog import is_family_id, is_risk_ref

# Checkpoint matrix: a risk-surface token -> the family it implies. The union of
# a claim's surfaces gives its family set (this is how the matrix's "add X if Y"
# escalations are realised).
RISK_SURFACE_FAMILIES: dict[str, FamilyId] = {
    # verdict path / public verdict wording
    "verdict": FamilyId.AUTHORITY_VERDICT,
    "score_status": FamilyId.AUTHORITY_VERDICT,
    "threshold": FamilyId.AUTHORITY_VERDICT,
    "confidence": FamilyId.AUTHORITY_VERDICT,
    "calibration": FamilyId.AUTHORITY_VERDICT,
    "judge_influence": FamilyId.AUTHORITY_VERDICT,
    "public_report": FamilyId.AUTHORITY_VERDICT,
    "report": FamilyId.AUTHORITY_VERDICT,
    "ci_verdict": FamilyId.AUTHORITY_VERDICT,
    "dashboard": FamilyId.AUTHORITY_VERDICT,
    "trace_export": FamilyId.AUTHORITY_VERDICT,
    # authority boundaries / source of truth / public contracts
    "contract_boundary": FamilyId.CONTRACT_BOUNDARY,
    "product_boundary": FamilyId.CONTRACT_BOUNDARY,
    "runtime_boundary": FamilyId.CONTRACT_BOUNDARY,
    "generated_authority": FamilyId.CONTRACT_BOUNDARY,
    "proposed_authority": FamilyId.CONTRACT_BOUNDARY,
    "source_of_truth": FamilyId.CONTRACT_BOUNDARY,
    "public_api": FamilyId.CONTRACT_BOUNDARY,
    "schema": FamilyId.CONTRACT_BOUNDARY,
    "build_contract": FamilyId.CONTRACT_BOUNDARY,
    # provenance / records / comparison
    "run_record": FamilyId.EVIDENCE_PROVENANCE,
    "scorecard": FamilyId.EVIDENCE_PROVENANCE,
    "diagnostics": FamilyId.EVIDENCE_PROVENANCE,
    "baseline": FamilyId.EVIDENCE_PROVENANCE,
    "regression": FamilyId.EVIDENCE_PROVENANCE,
    "retention": FamilyId.EVIDENCE_PROVENANCE,
    "deletion": FamilyId.EVIDENCE_PROVENANCE,
    "reproducibility": FamilyId.EVIDENCE_PROVENANCE,
    "provenance": FamilyId.EVIDENCE_PROVENANCE,
    "artifact_lineage": FamilyId.EVIDENCE_PROVENANCE,
    # EGTS proof
    "scenario": FamilyId.SCENARIO_CHECKER,
    "checker": FamilyId.SCENARIO_CHECKER,
    "fixture": FamilyId.SCENARIO_CHECKER,
    "required_suite": FamilyId.SCENARIO_CHECKER,
    "authored_expectation": FamilyId.SCENARIO_CHECKER,
    "egts_expectation": FamilyId.SCENARIO_CHECKER,
    # integration boundaries
    "integration": FamilyId.INTEGRATION_BOUNDARY,
    "runtime_route": FamilyId.INTEGRATION_BOUNDARY,
    "vendoring": FamilyId.INTEGRATION_BOUNDARY,
    "optional_lane": FamilyId.INTEGRATION_BOUNDARY,
    "rag": FamilyId.INTEGRATION_BOUNDARY,
    "data_policy": FamilyId.INTEGRATION_BOUNDARY,
    "external_judge": FamilyId.INTEGRATION_BOUNDARY,
    "external_integration": FamilyId.INTEGRATION_BOUNDARY,
}


def _explicit_gate_plan_families(
    gate_plan: dict[str, Any], blocked_on: list[str]
) -> list[FamilyId] | None:
    """Validate gate-plan family tokens; record blocks for invalid/risk-ref tokens.

    `gate_plan` is otherwise-arbitrary JSON, so a malformed `families` value
    (not an array, or non-string elements) must fail closed, not crash.
    """
    tokens = gate_plan.get("families")
    if tokens is None:
        return None
    if not isinstance(tokens, list):
        blocked_on.append(
            f"gate_plan.families must be an array of family ids, got {type(tokens).__name__}"
        )
        return None
    if not tokens:
        return None
    families: list[FamilyId] = []
    for token in tokens:
        if not isinstance(token, str):
            blocked_on.append(f"gate_plan.families entry {token!r} is not a string family id")
        elif is_family_id(token):
            families.append(FamilyId(token))
        elif is_risk_ref(token):
            blocked_on.append(
                f"gate_plan family {token!r} is a risk-catalog reference, not a family id; "
                "risk-catalog entries are supporting metadata only"
            )
        else:
            blocked_on.append(f"gate_plan family {token!r} is not a valid family id")
    return families


def _families_for_claim(
    claim: Claim, explicit_plan: list[FamilyId] | None
) -> tuple[set[FamilyId], bool]:
    """Return (routed families, was_explicit). Explicit pins skip inference."""
    if claim.expected_families:
        return set(claim.expected_families), True
    if explicit_plan:
        return set(explicit_plan), True
    inferred = {RISK_SURFACE_FAMILIES[s] for s in claim.risk_surfaces if s in RISK_SURFACE_FAMILIES}
    return inferred, False


def _inferred_families(claim: Claim) -> set[FamilyId]:
    return {RISK_SURFACE_FAMILIES[s] for s in claim.risk_surfaces if s in RISK_SURFACE_FAMILIES}


def route(pack: EvidencePack) -> RouterResult:
    """Route the pack's claims to the smallest family set, or BLOCKED."""
    blocked_on: list[str] = []
    if not pack.claims:
        blocked_on.append("gate plan selected Validator but no claim was provided")
        return RouterResult(status=Status.BLOCKED, blocked_on=blocked_on)

    explicit_plan = _explicit_gate_plan_families(pack.gate_plan, blocked_on)

    family_claims: dict[FamilyId, list[str]] = {}
    family_evidence: dict[FamilyId, set[str]] = {}
    warnings: list[str] = []
    for claim in pack.claims:
        fams, was_explicit = _families_for_claim(claim, explicit_plan)
        if not fams:
            blocked_on.append(
                f"claim {claim.id!r} cannot be routed: no expected_families, no gate_plan "
                "families, and no recognised risk_surfaces"
            )
            continue
        # An explicit pin (expected_families or gate_plan) skips inference. If the
        # claim's risk_surfaces imply a family the pin omits, that check is being
        # silently dropped — surface it as a warning (routing is unchanged so the
        # Execution Loop keeps its explicit scoping control).
        if was_explicit:
            omitted = _inferred_families(claim) - fams
            if omitted:
                names = ", ".join(sorted(f.value for f in omitted))
                warnings.append(
                    f"claim {claim.id!r} is pinned to "
                    f"{', '.join(sorted(f.value for f in fams))} but its risk_surfaces imply "
                    f"{names}, which will not be validated"
                )
        for fam in fams:
            family_claims.setdefault(fam, []).append(claim.id)
            family_evidence.setdefault(fam, set()).update(claim.required_artifacts)

    if blocked_on:
        # Keep coverage warnings even when another claim blocks routing, so the
        # diagnostic isn't lost until the unrelated blocker is fixed.
        return RouterResult(status=Status.BLOCKED, blocked_on=blocked_on, warnings=warnings)

    families = [
        RouterFamily(
            family_id=fam,
            claim_ids=sorted(family_claims[fam]),
            reason=f"{fam.value} selected for {len(family_claims[fam])} claim(s)",
            required_evidence=sorted(family_evidence[fam]),
        )
        for fam in sorted(family_claims, key=lambda f: f.value)
    ]
    return RouterResult(status=Status.PASS, families=families, warnings=warnings)
