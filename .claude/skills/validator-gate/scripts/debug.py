"""Non-authoritative debug trace for the validator-gate (VG-P2-5).

`validator.result.json` stays the only authority. This module builds a readable
*trace* of how the gate reached a verdict — the intermediate state the result
omits — for the first real runs (M1+): how each claim routed and why, which
family inspected which claim with which evidence, and how the index classified
the evidence (including artifacts materialized from adjacent gates). The trace is
deterministic and side-channel only; it never changes status, exit code, or the
result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts.contracts import FamilyFinding, FamilyId, RouterResult
    from scripts.families.base import Family
    from scripts.index import EvidenceIndex


def build_trace(
    *,
    index: EvidenceIndex,
    router_result: RouterResult,
    findings: list[FamilyFinding],
    registry: dict[FamilyId, Family],
    checkpoint: str,
    blocked_on: list[str] | None = None,
) -> dict[str, Any]:
    """Build the structured, JSON-able trace from the pipeline's intermediate state.

    `blocked_on` is the result's full blocker list (index + routing + family
    crash/unimplemented + uncovered claims), so the trace explains BLOCKED runs
    rather than looking clean while the verdict is BLOCKED.
    """
    registered = set(registry)
    by_authority = {
        authority.value: [a.id for a in arts]
        for authority, arts in index.normalized.by_authority.items()
        if arts
    }
    materialized = sorted(
        a.id for a in index.pack.artifacts if a.produced_by in {"scan-gate", "code-review"}
    )
    return {
        "gate": "validator",
        "checkpoint": checkpoint,
        "registry": sorted(f.value for f in registered),
        "blocked_on": list(blocked_on or []),
        "routing": {
            "status": router_result.status.value,
            "blocked_on": list(router_result.blocked_on),
            "warnings": list(router_result.warnings),
            "families": [
                {
                    "family_id": rf.family_id.value,
                    "claim_ids": list(rf.claim_ids),
                    "reason": rf.reason,
                    "required_evidence": list(rf.required_evidence),
                    "risk_references": list(rf.risk_references),
                    "implemented": rf.family_id in registered,
                }
                for rf in router_result.families
            ],
        },
        "evidence": {
            "by_authority": by_authority,
            "materialized_adjacent": materialized,
            "blocked_on": list(index.blocked_on),
            "warnings": list(index.warnings),
        },
        "coverage": [
            {
                "family_id": f.family_id.value,
                "claim_id": f.claim_id,
                "status": f.status.value,
                "evidence_refs": list(f.evidence_refs),
            }
            for f in findings
        ],
    }


def _items(values: list[str]) -> str:
    return ", ".join(values) if values else "(none)"


def render_trace(trace: dict[str, Any]) -> str:
    """Render the trace as a readable block (for stderr). A view, not authority."""
    lines = [
        f"validator-gate debug trace (checkpoint={trace['checkpoint']})",
        f"registry: {_items(trace['registry'])}",
    ]
    if trace["blocked_on"]:
        lines.append("blocked_on:")
        lines.extend(f"  ! {reason}" for reason in trace["blocked_on"])
    lines.append("")
    lines.append(f"routing: {trace['routing']['status']}")
    for rf in trace["routing"]["families"]:
        flag = "" if rf["implemented"] else "  [NOT IMPLEMENTED]"
        lines.append(
            f"  - {rf['family_id']} <- [{_items(rf['claim_ids'])}]  "
            f"({rf['reason']})  evidence: {_items(rf['required_evidence'])}{flag}"
        )
    for reason in trace["routing"]["blocked_on"]:
        lines.append(f"  ! {reason}")
    for warning in trace["routing"].get("warnings", []):
        lines.append(f"  ~ {warning}")

    ev = trace["evidence"]
    lines.append("")
    lines.append("evidence:")
    for authority, ids in ev["by_authority"].items():
        lines.append(f"  {authority}: {_items(ids)}")
    lines.append(f"  materialized adjacent: {_items(ev['materialized_adjacent'])}")
    lines.append(f"  blocked_on: {_items(ev['blocked_on'])}")
    lines.append(f"  warnings: {_items(ev['warnings'])}")

    lines.append("")
    lines.append("coverage:")
    for c in trace["coverage"]:
        lines.append(
            f"  {c['family_id']} / {c['claim_id']} -> {c['status']}  "
            f"evidence: {_items(c['evidence_refs'])}"
        )
    return "\n".join(lines) + "\n"
