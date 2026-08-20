"""authority_verdict family (VG-P1-3) — the highest-risk family.

Validates that exactly one product authority decides the run, and that no public
surface claims more than that verdict supports. Conventions in inline content:

- a product verdict/scorecard carries ``verdict`` (or ``status``): one of
  ``pass`` / ``pass_with_warnings`` / ``informational`` / ``blocked`` / ``fail``;
- a public surface (report/CI/dashboard/trace) carries ``claimed_status``;
- any artifact may carry ``decides_verdict: true`` to assert it decides the run.

Outcomes:
- FAIL: a non-product artifact decides the verdict.
- FAIL: more than one artifact claims to decide the verdict (duplicate authority).
- FAIL: product verdict artifacts conflict.
- FAIL: a public surface claims a stronger status than the product verdict.
- BLOCKED: no required evidence, or no product verdict to compare against.
- PASS: one product verdict, no usurper, public claims no stronger than it.
"""

from __future__ import annotations

from typing import Any

from scripts.contracts import ArtifactKind, Authority, FamilyFinding, FamilyId, Status
from scripts.families.base import FamilyContext, finding, probe

RISK_REF = "authority_verdict"

# How much success a status claims (higher = stronger). An overclaim is a public
# status ranked above the product verdict. Unknown statuses rank lowest so they
# never read as an overclaim.
_RANK = {"pass": 3, "pass_with_warnings": 2, "informational": 1, "blocked": 0, "fail": 0}
_KNOWN = frozenset(_RANK)
_VERDICT_KINDS = {ArtifactKind.VERDICT, ArtifactKind.SCORECARD, ArtifactKind.RUN_RECORD}
# A claim that touches one of these surfaces must be backed by a public artifact
# carrying claimed_status; otherwise there is nothing to check the wording against.
_PUBLIC_SURFACES = {"public_report", "report", "ci_verdict", "dashboard", "trace_export"}


def _norm(status: object) -> str | None:
    """Normalize a status string (case/whitespace) so 'PASS' == 'pass'."""
    return status.strip().lower() if isinstance(status, str) else None


def _verdict_value(content: dict[str, Any] | None) -> str | None:
    value = probe(content, "verdict")
    if value is None:
        value = probe(content, "status")
    return _norm(value)


def _block(ctx: FamilyContext, reason: str, remediation: str) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.AUTHORITY_VERDICT,
            Status.BLOCKED,
            reason=reason,
            remediation=remediation,
            risk_ref=RISK_REF,
        )
    ]


def _fail(
    ctx: FamilyContext, reason: str, remediation: str, evidence_refs: list[str]
) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.AUTHORITY_VERDICT,
            Status.FAIL,
            reason=reason,
            remediation=remediation,
            evidence_refs=evidence_refs,
            risk_ref=RISK_REF,
        )
    ]


def validate(ctx: FamilyContext) -> list[FamilyFinding]:
    required = list({a.id: a for a in ctx.index.required_artifacts(ctx.claim.id)}.values())
    if not required:
        return _block(
            ctx,
            "authority_verdict claim has no required artifacts to inspect",
            "Declare the product verdict/scorecard and any public-output artifacts "
            "this claim covers.",
        )

    # Exactly one authority may decide the run, and it must be product authority.
    deciders = [a for a in required if probe(a.content, "decides_verdict") is True]
    non_product = sorted(a.id for a in deciders if a.authority is not Authority.PRODUCT)
    if non_product:
        return _fail(
            ctx,
            f"non-product artifact(s) {non_product} are marked as deciding the product verdict",
            "Only the product Verdict Engine output may decide the verdict; "
            "downstream artifacts consume it.",
            non_product,
        )
    if len(deciders) > 1:
        ids = sorted(a.id for a in deciders)
        return _fail(
            ctx,
            f"multiple artifacts {ids} claim to decide the verdict (duplicate authority)",
            "Exactly one product artifact may be the effective verdict authority for a run.",
            ids,
        )

    # Establish the single effective product verdict.
    product_verdicts = [
        (a.id, _verdict_value(a.content))
        for a in required
        if a.authority is Authority.PRODUCT
        and a.kind in _VERDICT_KINDS
        and _verdict_value(a.content) is not None
    ]
    if not product_verdicts:
        return _block(
            ctx,
            "no product verdict or scorecard is present to establish verdict authority",
            "Include the product verdict/scorecard artifact the claim relies on.",
        )
    unknown_verdict = sorted(aid for aid, value in product_verdicts if value not in _KNOWN)
    if unknown_verdict:
        return _block(
            ctx,
            f"product verdict artifact(s) {unknown_verdict} carry an unrecognized verdict value",
            "Emit a known verdict (pass/pass_with_warnings/informational/blocked/fail).",
        )
    distinct = sorted({value for _, value in product_verdicts if value is not None})
    if len(distinct) > 1:
        ids = sorted(aid for aid, _ in product_verdicts)
        return _fail(
            ctx,
            f"product verdict artifacts conflict: {distinct} across {ids}",
            "Resolve to one effective product verdict before making a public claim.",
            ids,
        )
    product_verdict = distinct[0]

    # Gather public-surface claims (normalized). claimed_status is the proof being
    # validated, so an unrecognized value blocks rather than passes.
    publics = [
        (a.id, _norm(probe(a.content, "claimed_status")))
        for a in required
        if probe(a.content, "claimed_status") is not None
    ]
    unknown_claims = sorted(aid for aid, cs in publics if cs not in _KNOWN)
    if unknown_claims:
        return _block(
            ctx,
            f"public surface(s) {unknown_claims} carry an unrecognized claimed_status",
            "Use a known status so the public wording can be checked against the verdict.",
        )

    # A claim about public output must actually carry a public artifact to check.
    public_concern = bool({_norm(s) for s in ctx.claim.risk_surfaces} & _PUBLIC_SURFACES)
    if public_concern and not publics:
        return _block(
            ctx,
            "claim concerns public output but no public-surface artifact "
            "(claimed_status) is present",
            "Include the report/CI/dashboard/trace artifact whose wording the claim covers.",
        )

    # No public surface may claim more success than the product verdict supports.
    overclaimers = sorted(
        aid for aid, cs in publics if cs is not None and _RANK[cs] > _RANK[product_verdict]
    )
    if overclaimers:
        return _fail(
            ctx,
            f"public surface(s) {overclaimers} claim a status stronger than the "
            f"product verdict {product_verdict!r}",
            "Make the public status reflect the product verdict payload.",
            overclaimers,
        )

    return [
        finding(
            ctx,
            FamilyId.AUTHORITY_VERDICT,
            Status.PASS,
            reason=f"single effective product verdict {product_verdict!r}; "
            "public surfaces do not overclaim",
            evidence_refs=sorted(a.id for a in required),
        )
    ]
