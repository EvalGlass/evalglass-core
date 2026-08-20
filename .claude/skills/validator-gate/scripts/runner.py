"""Runner pipeline: evidence -> router -> families -> composer.

This is the orchestration the CLI and the Execution Loop adapter call. It fails
closed at every seam: an index-level boundary block propagates; a routing block
propagates; and a routed family with no registered implementation BLOCKS (it is
never silently treated as passing). The five real families register themselves
in later slices; until then `FAMILY_REGISTRY` is empty and any routed claim
blocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.composer import compose
from scripts.contracts import EvidencePack, FamilyId, Status, ValidatorResult
from scripts.debug import build_trace, render_trace
from scripts.evidence import EvidenceError, NormalizedEvidence
from scripts.families import (
    authority_verdict,
    contract_boundary,
    evidence_provenance,
    integration_boundary,
    scenario_checker,
)
from scripts.families.base import Family, FamilyContext
from scripts.index import EvidenceIndex
from scripts.router import route

if TYPE_CHECKING:
    from typing import TextIO

# All five canonical families are registered.
FAMILY_REGISTRY: dict[FamilyId, Family] = {
    FamilyId.CONTRACT_BOUNDARY: contract_boundary.validate,
    FamilyId.AUTHORITY_VERDICT: authority_verdict.validate,
    FamilyId.EVIDENCE_PROVENANCE: evidence_provenance.validate,
    FamilyId.SCENARIO_CHECKER: scenario_checker.validate,
    FamilyId.INTEGRATION_BOUNDARY: integration_boundary.validate,
}


def run_validation(
    source: NormalizedEvidence | EvidencePack | dict[str, Any] | str | Path,
    *,
    checkpoint: str | None = None,
    registry: dict[FamilyId, Family] | None = None,
    trace_sink: TextIO | None = None,
) -> ValidatorResult:
    """Validate an evidence pack and return one ValidatorResult.

    When `trace_sink` is given, a non-authoritative debug trace (routing,
    coverage, evidence classification) is written to it. It never changes the
    result, status, or exit code.
    """
    registry = FAMILY_REGISTRY if registry is None else registry
    # The runner is fail-closed: an unreadable/invalid pack becomes a BLOCKED
    # result, never a crash, for dict/path callers.
    try:
        index = EvidenceIndex.build(source)
    except EvidenceError as exc:
        return compose(
            checkpoint=checkpoint or "unknown",
            claim_ids=[],
            findings=[],
            evidence_blocked_on=[f"evidence: {exc}"],
        )
    pack = index.pack
    cp = checkpoint or pack.checkpoint

    blocked_on = list(index.blocked_on)
    router_result = route(pack)
    if router_result.status is Status.BLOCKED:
        blocked_on.extend(router_result.blocked_on)

    findings = []
    families_run: list[str] = []
    risk_refs: set[str] = set()
    for routed in router_result.families:
        impl = registry.get(routed.family_id)
        if impl is None:
            blocked_on.append(
                f"family {routed.family_id.value!r} is selected for claim(s) "
                f"{', '.join(routed.claim_ids)} but has no implementation yet"
            )
            continue
        families_run.append(routed.family_id.value)
        risk_refs.update(routed.risk_references)
        for claim_id in routed.claim_ids:
            claim = index.claim(claim_id)
            if claim is None:
                continue
            try:
                findings.extend(impl(FamilyContext(index=index, claim=claim)))
            except Exception as exc:  # a crashing family must fail closed, not raise
                blocked_on.append(
                    f"family {routed.family_id.value!r} crashed on claim {claim_id!r}: "
                    f"{exc.__class__.__name__}: {exc}"
                )

    result = compose(
        checkpoint=cp,
        claim_ids=[c.id for c in pack.claims],
        findings=findings,
        families_run=families_run,
        evidence_blocked_on=blocked_on,
        warnings=[*index.warnings, *router_result.warnings],
        risk_references_used=sorted(risk_refs),
    )

    if trace_sink is not None:
        # Build the trace from the composed result so its blocked_on matches the
        # authoritative verdict (incl. family crash / unimplemented / uncovered).
        trace = build_trace(
            index=index,
            router_result=router_result,
            findings=findings,
            registry=registry,
            checkpoint=cp,
            blocked_on=result.blocked_on,
        )
        trace_sink.write(render_trace(trace))

    return result
