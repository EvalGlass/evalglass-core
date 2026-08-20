"""Claim/artifact evidence index (VG-P0-3).

A thin, deterministic query layer over `NormalizedEvidence` so the router and
the semantic families can ask "what proves or blocks this claim?" without
re-parsing the raw pack. It is a lookup surface, not a rule engine: it makes
evidence easy to inspect and preserves artifact lineage (claim_ids, produced_by)
for findings.

The index inherits the reader's `blocked_on` (boundary problems) and adds claim
quality blocks: a claim with an empty id or empty text cannot be validated, so
it fails closed before any family runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.contracts import ArtifactKind, ArtifactRef, Authority, Claim, EvidencePack, FamilyId
from scripts.evidence import NormalizedEvidence, normalize, read_evidence


@dataclass
class EvidenceIndex:
    """Deterministic lookup surface over a normalized evidence pack."""

    normalized: NormalizedEvidence
    blocked_on: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls, source: NormalizedEvidence | EvidencePack | dict[str, Any] | str | Path
    ) -> EvidenceIndex:
        if isinstance(source, NormalizedEvidence):
            normalized = source
        elif isinstance(source, EvidencePack):
            normalized = normalize(source)
        else:
            normalized = read_evidence(source)
        blocked_on = list(normalized.blocked_on)
        claims = normalized.pack.claims
        for position, claim in enumerate(claims):
            if not claim.id.strip():
                blocked_on.append(
                    f"claim at position {position} has an empty id and cannot be validated"
                )
            if not claim.text.strip():
                label = repr(claim.id) if claim.id.strip() else f"position {position}"
                blocked_on.append(f"claim {label} has empty text and cannot be validated")
        # Duplicate claim ids make claim() ambiguous (it returns the first), so a
        # second claim's required evidence would be silently ignored. Fail closed.
        counts: dict[str, int] = {}
        for claim in claims:
            counts[claim.id] = counts.get(claim.id, 0) + 1
        for dup in sorted(cid for cid, n in counts.items() if n > 1 and cid.strip()):
            blocked_on.append(
                f"claim id {dup!r} is declared more than once; claim identity is ambiguous"
            )
        return cls(normalized=normalized, blocked_on=blocked_on, warnings=list(normalized.warnings))

    # --- structural -----------------------------------------------------------

    @property
    def pack(self) -> EvidencePack:
        return self.normalized.pack

    @property
    def ok(self) -> bool:
        return not self.blocked_on

    def claims(self) -> list[Claim]:
        return list(self.pack.claims)

    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.pack.claims if c.id == claim_id), None)

    # --- artifact lookups -------------------------------------------------------

    def artifact(self, ref: str) -> ArtifactRef | None:
        """Resolve an artifact by id, falling back to its declared path."""
        by_id = self.normalized.by_id
        if ref in by_id:
            return by_id[ref]
        return next((a for a in self.pack.artifacts if a.path == ref), None)

    def artifacts_by_authority(self, authority: Authority) -> list[ArtifactRef]:
        """Artifacts the boundary classifies under this authority (pack order)."""
        return list(self.normalized.by_authority.get(authority, []))

    def artifacts_by_kind(self, kind: ArtifactKind) -> list[ArtifactRef]:
        return [a for a in self.pack.artifacts if a.kind is kind]

    # --- claim <-> evidence -----------------------------------------------------

    def required_artifacts(self, claim_id: str) -> list[ArtifactRef]:
        """Resolved refs for a claim's required artifacts that are present."""
        claim = self.claim(claim_id)
        if claim is None:
            return []
        resolved = [self.artifact(ref) for ref in claim.required_artifacts]
        return [a for a in resolved if a is not None]

    def missing_artifacts(self, claim_id: str) -> list[str]:
        """Required artifact refs with no matching artifact — visible before validation."""
        claim = self.claim(claim_id)
        if claim is None:
            return []
        return [ref for ref in claim.required_artifacts if self.artifact(ref) is None]

    def claims_for_family(self, family_id: FamilyId) -> list[Claim]:
        return [c for c in self.pack.claims if family_id in c.expected_families]
