"""Proposed-reference drafting and validation handoff (Epic B, B5).

There is a wide gap between "no reference" and "validated gold". Silver/proposed references are
useful for exercising reference metrics on the first useful iteration — but they must never be
mistaken for validated gold, and EvalGlass must never validate them for the host.

This module provides that lifecycle, host-owned and fail-closed:

    draft -> proposed -> reviewed -> validated -> retired

A drafted reference always starts ``proposed`` (never ``validated``), records its source evidence,
generation method, author, version, and limitations, and is refused entirely when it would leak the
candidate output (a reference that merely copies the model's output is circular, not gold). Only an
explicit host-owned :class:`ReviewRecord` — with a human reviewer who is neither the generator nor
any agent identity — can move a set to ``validated``; EvalGlass verifies that record, it never
writes ``validated`` itself. Reference content is content-addressed, so any change breaks
comparability for a consuming metric.

Authority is unchanged and reused: a proposed reference maps to a ``proposed`` dataset status, so it
scores informationally and cannot support a validated-dataset gate until the host validates it.

Stdlib + core only.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core import DatasetStatus, Diagnostic, Severity

#: Generator/agent identities that may draft references but can NEVER be a validating reviewer.
#: Matching is substring-insensitive so ``EvalGlass reference-draft`` and ``the agent`` are caught.
_AGENT_IDENTITY_MARKERS = ("evalglass", "agent", "assistant", "plugin", "codex", "claude", "bot")


class ReferenceStatus(enum.StrEnum):
    """The lifecycle state of a reference set — proposed until a host validates it."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    VALIDATED = "validated"
    RETIRED = "retired"


#: Allowed forward/lateral transitions; anything else (e.g. draft->validated) fails closed.
_ALLOWED_TRANSITIONS: dict[ReferenceStatus, frozenset[ReferenceStatus]] = {
    ReferenceStatus.DRAFT: frozenset({ReferenceStatus.PROPOSED, ReferenceStatus.RETIRED}),
    ReferenceStatus.PROPOSED: frozenset({ReferenceStatus.REVIEWED, ReferenceStatus.RETIRED}),
    ReferenceStatus.REVIEWED: frozenset(
        {ReferenceStatus.VALIDATED, ReferenceStatus.PROPOSED, ReferenceStatus.RETIRED}
    ),
    ReferenceStatus.VALIDATED: frozenset({ReferenceStatus.RETIRED, ReferenceStatus.REVIEWED}),
    ReferenceStatus.RETIRED: frozenset(),
}

#: A proposed reference maps to a proposed dataset — informational, cannot gate (reuses authority).
_STATUS_TO_DATASET: dict[ReferenceStatus, DatasetStatus] = {
    ReferenceStatus.DRAFT: DatasetStatus.PROPOSED,
    ReferenceStatus.PROPOSED: DatasetStatus.PROPOSED,
    ReferenceStatus.REVIEWED: DatasetStatus.PROPOSED,
    ReferenceStatus.VALIDATED: DatasetStatus.VALIDATED,
    ReferenceStatus.RETIRED: DatasetStatus.RETIRED,
}


class ReferenceError(Exception):
    """A fail-closed reference-lifecycle error (a setup error, never a verdict)."""


def can_transition(current: ReferenceStatus, target: ReferenceStatus) -> bool:
    """Whether ``current -> target`` is an allowed lifecycle transition."""
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


def is_agent_identity(who: str) -> bool:
    """Whether ``who`` is an agent/tool identity that may draft but never validate a reference."""
    lowered = who.lower()
    return any(marker in lowered for marker in _AGENT_IDENTITY_MARKERS)


def dataset_status_for(status: ReferenceStatus) -> DatasetStatus:
    """The dataset status a reference set of this lifecycle state confers (reuses authority)."""
    return _STATUS_TO_DATASET[status]


def _normalize(value: Any) -> str:
    """A whitespace/case-insensitive canonical form for leakage comparison."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return " ".join(text.lower().split())


def detect_leakage(candidate_output: Any, reference_value: Any) -> str | None:
    """Return a leakage reason if the reference merely copies the candidate output, else ``None``.

    Sensitivity: an exact or whitespace/case-only-different copy of the candidate is leakage (a
    metric graded against a reference derived from the very output it scores is circular).
    Specificity: a genuinely different reference that merely shares words is allowed.
    """
    if _normalize(candidate_output) == _normalize(reference_value):
        return "reference is identical to the candidate output (leakage)"
    return None


@dataclass(frozen=True)
class ReviewRecord:
    """A host-owned review decision. EvalGlass verifies it; it never writes one itself."""

    reviewer: str
    decision: str  # "validated" | "rejected"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {"reviewer": self.reviewer, "decision": self.decision}
        if self.notes:
            out["notes"] = self.notes
        return out

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        if not isinstance(data, Mapping) or "reviewer" not in data or "decision" not in data:
            raise ReferenceError("review record needs a 'reviewer' and a 'decision'")
        return cls(
            reviewer=str(data["reviewer"]),
            decision=str(data["decision"]),
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True)
class ReferenceItem:
    """One proposed reference value plus its provenance (source evidence, method, applicability)."""

    example_id: str
    value: Any
    source_evidence_refs: tuple[str, ...] = ()
    limitations: str = ""
    applies_to: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"example_id": self.example_id, "value": self.value}
        if self.source_evidence_refs:
            out["source_evidence_refs"] = list(self.source_evidence_refs)
        if self.limitations:
            out["limitations"] = self.limitations
        if self.applies_to:
            out["applies_to"] = list(self.applies_to)
        return out

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        if not isinstance(data, Mapping) or "example_id" not in data or "value" not in data:
            raise ReferenceError("reference item needs an 'example_id' and a 'value'")
        return cls(
            example_id=str(data["example_id"]),
            value=data["value"],
            source_evidence_refs=tuple(str(r) for r in data.get("source_evidence_refs", [])),
            limitations=str(data.get("limitations", "")),
            applies_to=tuple(str(a) for a in data.get("applies_to", [])),
        )


@dataclass(frozen=True)
class ReferenceSet:
    """A versioned set of proposed references plus its lifecycle state and (optional) review."""

    name: str
    status: ReferenceStatus
    method: str
    author: str
    version: str = "1"
    items: tuple[ReferenceItem, ...] = ()
    review: ReviewRecord | None = None

    def content_digest(self) -> str:
        """A content address over the reference values (any change breaks comparability)."""
        payload = [[i.example_id, i.value] for i in self.items]
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": "evalglass.reference-set/1",
            "name": self.name,
            "status": self.status.value,
            "method": self.method,
            "author": self.author,
            "version": self.version,
            "content_digest": self.content_digest(),
            "items": [i.to_dict() for i in self.items],
        }
        if self.review is not None:
            out["review"] = self.review.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        if not isinstance(data, Mapping):
            raise ReferenceError("reference set must be a mapping")
        try:
            status = ReferenceStatus(data["status"])
        except (KeyError, ValueError) as exc:
            raise ReferenceError(f"reference set has no valid status: {exc}") from exc
        return cls(
            name=str(data.get("name", "references")),
            status=status,
            method=str(data.get("method", "")),
            author=str(data.get("author", "")),
            version=str(data.get("version", "1")),
            items=tuple(ReferenceItem.from_dict(i) for i in data.get("items", [])),
            review=ReviewRecord.from_dict(data["review"]) if data.get("review") else None,
        )


def draft_reference_set(
    rows: Sequence[Mapping[str, Any]],
    *,
    name: str,
    method: str,
    author: str,
    reference_field: str,
    candidate_field: str,
) -> tuple[ReferenceSet, list[Diagnostic]]:
    """Draft a PROPOSED reference set from rows, refusing any item that would leak the candidate.

    A drafted set is always ``proposed`` — never validated. A row whose proposed reference is a copy
    of its candidate output yields a leakage diagnostic and NO reference item (no fabricated gold);
    a row missing an ``example_id`` or the reference field is skipped with a diagnostic.
    """
    items: list[ReferenceItem] = []
    diagnostics: list[Diagnostic] = []
    for idx, row in enumerate(rows):
        example_id = row.get("example_id")
        if not example_id:
            diagnostics.append(_diag("reference_no_example_id", f"row {idx} has no example_id"))
            continue
        if reference_field not in row:
            diagnostics.append(
                _diag("reference_missing_value", f"{example_id}: no '{reference_field}' to draft")
            )
            continue
        value = row[reference_field]
        leak = detect_leakage(row.get(candidate_field), value)
        if leak is not None:
            diagnostics.append(_diag("reference_leakage", f"{example_id}: {leak}"))
            continue
        refs = row.get("source_evidence_refs")
        items.append(
            ReferenceItem(
                example_id=str(example_id),
                value=value,
                source_evidence_refs=tuple(str(r) for r in refs) if isinstance(refs, list) else (),
            )
        )
    ref_set = ReferenceSet(
        name=name,
        status=ReferenceStatus.PROPOSED,  # never validated at draft time
        method=method,
        author=author,
        items=tuple(items),
    )
    return ref_set, diagnostics


def promote(
    ref_set: ReferenceSet, target: ReferenceStatus, *, review: ReviewRecord | None = None
) -> ReferenceSet:
    """Return ``ref_set`` at ``target`` status, fail-closed on lifecycle and self-approval rules.

    Only a host-owned :class:`ReviewRecord` whose reviewer is neither the set's author nor any agent
    identity can reach ``validated`` — EvalGlass verifies the record, it never fabricates one. A
    disallowed transition (proposed->validated skipping review, or draft->validated) is refused.
    """
    if not can_transition(ref_set.status, target):
        raise ReferenceError(
            f"cannot move a reference set from {ref_set.status.value} to {target.value}"
        )
    if target is ReferenceStatus.VALIDATED:
        if review is None or review.decision != "validated":
            raise ReferenceError("validating a reference set requires a host review record")
        if is_agent_identity(review.reviewer):
            raise ReferenceError(
                f"reviewer {review.reviewer!r} is an agent identity and cannot validate a reference"
            )
        if review.reviewer.strip().lower() == ref_set.author.strip().lower():
            raise ReferenceError("the reference author cannot be its own validating reviewer")
    return ReferenceSet(
        name=ref_set.name,
        status=target,
        method=ref_set.method,
        author=ref_set.author,
        version=ref_set.version,
        items=ref_set.items,
        review=review if review is not None else ref_set.review,
    )


def validate_reference_set(
    ref_set: ReferenceSet, *, available_evidence: frozenset[str] | None = None
) -> list[Diagnostic]:
    """Structural + evidence-resolution checks (never mutates status). Returns diagnostics.

    Each item's declared source evidence refs must resolve against ``available_evidence`` (when
    supplied); an unresolved ref is a typed diagnostic, so a reference built on missing/tampered
    evidence is visible rather than silently trusted.
    """
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    for item in ref_set.items:
        if item.example_id in seen:
            diagnostics.append(
                _diag("reference_duplicate_id", f"duplicate example_id {item.example_id}")
            )
        seen.add(item.example_id)
        if available_evidence is not None:
            for ref in item.source_evidence_refs:
                if ref not in available_evidence:
                    diagnostics.append(
                        _diag(
                            "reference_evidence_unresolved",
                            f"{item.example_id}: no evidence {ref!r}",
                        )
                    )
    return diagnostics


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.WARNING, message=message)
