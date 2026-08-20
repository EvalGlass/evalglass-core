"""Evidence-pack reader + source-boundary validator (VG-P0-2).

This is the durability mechanism for the whole gate: instead of assuming where
artifacts live, Validator reads the *declared* source boundary from the pack and
classifies each artifact by authority. It is strict about authority direction
and flexible about path shape.

`normalize` never raises; it returns a `NormalizedEvidence` whose `blocked_on`
records trust-critical structural problems (a downstream BLOCKED). A pack that
cannot even be parsed/validated is a different failure: `load_pack` raises
`EvidenceError` so the caller can surface a setup problem rather than a quality
verdict.

Trust-critical (→ blocked_on, fail closed):
- the source boundary is absent while claims exist (authority direction unknown);
- a boundary bucket name is not one of the seven canonical authorities;
- an artifact's declared authority contradicts the bucket it is listed under,
  or the same artifact is listed under two different authorities;
- a claim's required artifact is absent, stale, or outside the boundary.

An artifact that no claim requires and that the boundary does not classify is a
warning (it simply cannot satisfy required proof), not a block.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.contracts import (
    ArtifactRef,
    Authority,
    ContractError,
    EvidencePack,
)

# Boundary bucket name -> the authority it confers. Note `external_contracts`
# (the boundary bucket, per EVIDENCE_PACK.md) maps to Authority.EXTERNAL.
BUCKET_TO_AUTHORITY: dict[str, Authority] = {
    "product": Authority.PRODUCT,
    "egts": Authority.EGTS,
    "execution_loop": Authority.EXECUTION_LOOP,
    "scan_gate": Authority.SCAN_GATE,
    "validator_gate": Authority.VALIDATOR_GATE,
    "generated_or_proposed": Authority.GENERATED_OR_PROPOSED,
    "external_contracts": Authority.EXTERNAL,
}
CANONICAL_BUCKETS: frozenset[str] = frozenset(BUCKET_TO_AUTHORITY)


class EvidenceError(ValueError):
    """Raised when an evidence pack cannot be loaded or parsed at all."""


@dataclass
class NormalizedEvidence:
    """The reader's output: artifacts classified by authority, plus problems.

    `blocked_on` holds trust-critical structural problems; if it is empty the
    pack is structurally trustworthy (`ok`). `warnings` holds non-critical
    notes. `by_id` and `by_authority` are the lookup surfaces the claim/artifact
    index (next slice) and the families build on.
    """

    pack: EvidencePack
    by_id: dict[str, ArtifactRef] = field(default_factory=dict)
    by_authority: dict[Authority, list[ArtifactRef]] = field(default_factory=dict)
    blocked_on: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocked_on


def load_pack(source: dict[str, Any] | str | Path) -> EvidencePack:
    """Load + contract-validate an evidence pack from a dict or a JSON file.

    Raises EvidenceError on unreadable/unparseable input or contract violation.
    """
    if isinstance(source, dict):
        data = source
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EvidenceError(f"cannot read evidence pack {path}: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"evidence pack {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError("evidence pack must be a JSON object")
    try:
        return EvidencePack.from_dict(data)
    except (ContractError, TypeError, AttributeError) as exc:
        # The contract layer fails closed on bad types; this is belt-and-braces
        # so load_pack always honors its EvidenceError contract for bad input.
        raise EvidenceError(f"evidence pack violates the contract: {exc}") from exc


def _authorities_for(art: ArtifactRef, boundary: dict[str, list[str]]) -> list[Authority]:
    """Every bucket authority whose entry list names this artifact (by id or path)."""
    keys = {art.id}
    if art.path is not None:
        keys.add(art.path)
    found: list[Authority] = []
    for bucket, entries in boundary.items():
        auth = BUCKET_TO_AUTHORITY.get(bucket)
        if auth is None:
            continue  # unknown bucket already flagged elsewhere
        if keys & set(entries):
            found.append(auth)
    return found


def normalize(pack: EvidencePack) -> NormalizedEvidence:
    """Classify artifacts by authority and record trust-critical problems."""
    blocked_on: list[str] = []
    warnings: list[str] = []
    by_id = {a.id: a for a in pack.artifacts}
    by_path = {a.path: a for a in pack.artifacts if a.path is not None}
    by_authority: dict[Authority, list[ArtifactRef]] = {a: [] for a in Authority}
    boundary = pack.source_boundary

    # Duplicate artifact ids make identity ambiguous: by_id keeps only one while
    # classification sees both, so a required id could pass or block on list
    # order. Fail closed instead.
    counts: dict[str, int] = {}
    for art in pack.artifacts:
        counts[art.id] = counts.get(art.id, 0) + 1
    for dup in sorted(i for i, n in counts.items() if n > 1):
        blocked_on.append(
            f"artifact id {dup!r} is declared more than once; artifact identity is ambiguous"
        )

    # Authority direction must be declared when there is anything to validate.
    if pack.claims and not boundary:
        blocked_on.append(
            "source_boundary does not identify authoritative artifacts for the selected claims"
        )

    # Unknown bucket names break authority direction -> fail closed.
    for bucket in boundary:
        if bucket not in CANONICAL_BUCKETS:
            blocked_on.append(
                f"source_boundary: unknown authority bucket {bucket!r}; "
                f"expected one of {', '.join(sorted(CANONICAL_BUCKETS))}"
            )

    # Classify each artifact against the boundary.
    in_boundary: set[str] = set()
    for art in pack.artifacts:
        auths = _authorities_for(art, boundary)
        if not auths:
            continue  # outside the boundary; required-check handles relevance
        in_boundary.add(art.id)
        distinct = set(auths)
        if len(distinct) > 1:
            listed = ", ".join(sorted(a.value for a in distinct))
            blocked_on.append(
                f"artifact {art.id!r} is listed under conflicting authorities ({listed}); "
                "an artifact has exactly one source-of-truth authority"
            )
            continue
        bucket_auth = auths[0]
        if bucket_auth != art.authority:
            blocked_on.append(
                f"artifact {art.id!r} declares authority {art.authority.value!r} "
                f"but is listed under the {bucket_auth.value!r} boundary"
            )
            continue
        by_authority[art.authority].append(art)

    # A claim's required artifacts must be present, current, and in the boundary.
    required: set[tuple[str, str]] = {
        (claim.id, ref) for claim in pack.claims for ref in claim.required_artifacts
    }
    for claim_id, ref in sorted(required):
        found = by_id.get(ref) or by_path.get(ref)
        if found is None:
            blocked_on.append(
                f"required artifact {ref!r} for claim {claim_id!r} is absent from the evidence pack"
            )
        elif found.stale:
            blocked_on.append(f"required artifact {ref!r} for claim {claim_id!r} is stale")
        elif found.id not in in_boundary:
            blocked_on.append(
                f"required artifact {ref!r} for claim {claim_id!r} "
                "is outside the declared source boundary"
            )

    # Unclassified artifacts that no claim requires are non-critical notes.
    required_refs = {ref for _, ref in required}
    for art in pack.artifacts:
        if (
            art.id not in in_boundary
            and art.id not in required_refs
            and (art.path not in required_refs)
        ):
            warnings.append(
                f"artifact {art.id!r} is not declared in the source boundary; "
                "it cannot satisfy required proof"
            )

    return NormalizedEvidence(
        pack=pack,
        by_id=by_id,
        by_authority=by_authority,
        blocked_on=blocked_on,
        warnings=warnings,
    )


def read_evidence(source: dict[str, Any] | str | Path) -> NormalizedEvidence:
    """Convenience: load_pack + normalize."""
    return normalize(load_pack(source))
