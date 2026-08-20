"""Shared primitives for the semantic families.

A family is a callable ``(FamilyContext) -> list[FamilyFinding]``: it receives
one claim plus the evidence index and returns one finding per claim it
validates. It encodes a durable invariant, never a file layout — so it reads
artifact content through the tolerant `probe` accessor rather than importing
product dataclasses (the EvalGlass product is still a skeleton).

Outcome discipline (shared by every family):
- required evidence absent / outside boundary / stale -> BLOCKED;
- evidence present and contradicts the invariant -> FAIL;
- evidence present and consistent -> PASS.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scripts.contracts import Claim, FamilyFinding, FamilyId, Status
from scripts.index import EvidenceIndex


@dataclass
class FamilyContext:
    """What a family needs to validate one claim: the claim + the evidence index."""

    index: EvidenceIndex
    claim: Claim


# A family validates one claim and returns its finding(s).
Family = Callable[[FamilyContext], list[FamilyFinding]]


def probe(content: dict[str, Any] | None, dotted_path: str, default: Any = None) -> Any:
    """Read a nested field from an artifact's inline content by dotted path.

    Tolerant by design: a missing artifact (None), missing key, or non-mapping
    intermediate yields the default. This keeps families decoupled from the
    product's concrete shapes — they assert invariants over whatever typed
    fields the evidence carries.
    """
    if content is None:
        return default
    current: Any = content
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def finding(
    ctx: FamilyContext,
    family_id: FamilyId,
    status: Status,
    *,
    reason: str,
    remediation: str = "",
    evidence_refs: list[str] | None = None,
    risk_ref: str | None = None,
) -> FamilyFinding:
    """Construct a finding for the context's claim (small ergonomic helper)."""
    return FamilyFinding(
        family_id=family_id,
        claim_id=ctx.claim.id,
        status=status,
        evidence_refs=evidence_refs or [],
        reason=reason,
        remediation=remediation,
        risk_ref=risk_ref,
    )
