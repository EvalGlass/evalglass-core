"""contract_boundary family (VG-P1-2).

Protects authority direction: product, EGTS, runtime, generated/proposed, and
external artifacts must not be confused for one another. The Execution Loop
marks how an artifact is *used* in its inline content; this family compares that
usage against the artifact's declared ``authority`` and fails closed on a
boundary violation.

Usage signals (inline ``content``):
- ``acts_as``: ``"product"`` / ``"canonical"`` — the artifact is being treated
  as the canonical product source of truth.
- ``authoritative``: ``true`` — same intent, boolean form.
- ``promoted``: ``true`` — a generated/proposed artifact promoted to canonical.

Outcomes:
- FAIL: a non-product artifact acts as product authority.
- FAIL: a generated/proposed artifact is promoted to canonical.
- FAIL: two artifacts act as the same canonical product authority.
- PASS: authority boundaries are preserved (non-product artifacts present but
  not used as product authority).
"""

from __future__ import annotations

from typing import Any

from scripts.contracts import Authority, FamilyFinding, FamilyId, Status
from scripts.families.base import FamilyContext, finding, probe

RISK_REF = "contract_architecture"


def _acts_as_product(content: dict[str, Any] | None) -> bool:
    return (
        probe(content, "acts_as") in {"product", "canonical"}
        or probe(content, "authoritative") is True
    )


def _is_promoted(content: dict[str, Any] | None) -> bool:
    return probe(content, "promoted") is True or _acts_as_product(content)


def validate(ctx: FamilyContext) -> list[FamilyFinding]:
    # Dedupe by id: a claim may reference the same artifact twice, or by both id
    # and path, and that must not look like two sources of truth.
    required = list({a.id: a for a in ctx.index.required_artifacts(ctx.claim.id)}.values())

    # A contract_boundary claim with nothing to inspect cannot be proven.
    if not required:
        return [
            finding(
                ctx,
                FamilyId.CONTRACT_BOUNDARY,
                Status.BLOCKED,
                reason="contract_boundary claim has no required artifacts to inspect",
                remediation="Declare the product/contract artifacts this claim depends on.",
                risk_ref=RISK_REF,
            )
        ]

    # A non-product artifact presented as product authority breaks the boundary.
    impostors = [
        a for a in required if _acts_as_product(a.content) and a.authority is not Authority.PRODUCT
    ]
    if impostors:
        ids = sorted(a.id for a in impostors)
        worst = impostors[0]
        return [
            finding(
                ctx,
                FamilyId.CONTRACT_BOUNDARY,
                Status.FAIL,
                reason=(
                    f"artifact(s) {ids} carry {worst.authority.value!r} authority but are used "
                    "as the product source of truth; non-product authority cannot satisfy a "
                    "product claim"
                ),
                remediation="Back the claim with a product-authority artifact, or stop "
                "treating the non-product artifact as canonical.",
                evidence_refs=ids,
                risk_ref=RISK_REF,
            )
        ]

    # A generated/proposed artifact promoted to canonical is unapproved authority.
    promoted = [
        a
        for a in required
        if a.authority is Authority.GENERATED_OR_PROPOSED and _is_promoted(a.content)
    ]
    if promoted:
        ids = sorted(a.id for a in promoted)
        return [
            finding(
                ctx,
                FamilyId.CONTRACT_BOUNDARY,
                Status.FAIL,
                reason=f"generated/proposed artifact(s) {ids} are promoted to "
                "canonical without approval",
                remediation="Keep generated/proposed artifacts non-authoritative "
                "until a human validates them.",
                evidence_refs=ids,
                risk_ref=RISK_REF,
            )
        ]

    # Two artifacts acting as the same canonical product authority is a duplicate
    # source of truth.
    canonical = sorted(
        a.id for a in required if a.authority is Authority.PRODUCT and _acts_as_product(a.content)
    )
    if len(canonical) > 1:
        return [
            finding(
                ctx,
                FamilyId.CONTRACT_BOUNDARY,
                Status.FAIL,
                reason=f"multiple artifacts {canonical} act as the canonical "
                "product authority for one claim",
                remediation="Designate exactly one canonical product source of truth.",
                evidence_refs=canonical,
                risk_ref=RISK_REF,
            )
        ]

    return [
        finding(
            ctx,
            FamilyId.CONTRACT_BOUNDARY,
            Status.PASS,
            reason="authority boundaries preserved: no non-product artifact "
            "is used as product authority",
            evidence_refs=sorted(a.id for a in required),
        )
    ]
