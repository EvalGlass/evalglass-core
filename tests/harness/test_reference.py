"""Proposed-reference lifecycle + validation handoff (Epic B, B5).

Sensitivity: a drafted reference starts proposed and never validates itself; a candidate-copy is
refused as leakage; the agent can never be the validating reviewer; a skipped lifecycle transition
fails closed. Specificity: a genuinely different reference is allowed, and a host review record by a
distinct human validates.
"""

from __future__ import annotations

import pytest

from evalglass.core import DatasetStatus
from evalglass.harness.reference import (
    ReferenceError,
    ReferenceSet,
    ReferenceStatus,
    ReviewRecord,
    dataset_status_for,
    detect_leakage,
    draft_reference_set,
    promote,
    validate_reference_set,
)


def _rows() -> list[dict[str, object]]:
    return [
        {"example_id": "c1", "candidate": "The capital is Paris.", "reference": "Paris"},
        {"example_id": "c2", "candidate": "42", "reference": "42"},  # leakage (identical)
    ]


# --------------------------------------------------------------------------- #
# Drafting: always proposed, leakage refused
# --------------------------------------------------------------------------- #


def test_draft_starts_proposed_and_refuses_leakage() -> None:
    ref_set, diagnostics = draft_reference_set(
        _rows(),
        name="silver",
        method="host-heuristic",
        author="evalglass:reference-draft",
        reference_field="reference",
        candidate_field="candidate",
    )
    assert ref_set.status is ReferenceStatus.PROPOSED  # never validated at draft
    # c2's reference is a copy of the candidate → leakage → no item, a diagnostic instead.
    assert [i.example_id for i in ref_set.items] == ["c1"]
    assert any(d.code == "reference_leakage" for d in diagnostics)


def test_leakage_sensitivity_and_specificity() -> None:
    # Sensitivity: identical (modulo whitespace/case) → flagged.
    assert detect_leakage("Paris", "  paris ") is not None
    # Specificity: genuinely different reference that shares a word → allowed.
    assert detect_leakage("The capital of France is Paris.", "Paris") is None


# --------------------------------------------------------------------------- #
# Lifecycle transitions — fail closed
# --------------------------------------------------------------------------- #


def _proposed() -> ReferenceSet:
    ref_set, _ = draft_reference_set(
        [{"example_id": "c1", "candidate": "x", "reference": "gold"}],
        name="silver",
        method="m",
        author="host:alice",
        reference_field="reference",
        candidate_field="candidate",
    )
    return ref_set


def test_cannot_skip_to_validated() -> None:
    proposed = _proposed()
    with pytest.raises(ReferenceError, match="cannot move"):
        promote(proposed, ReferenceStatus.VALIDATED)  # proposed->validated skips review


def test_validated_requires_a_review_record() -> None:
    reviewed = promote(_proposed(), ReferenceStatus.REVIEWED)
    with pytest.raises(ReferenceError, match="requires a host review record"):
        promote(reviewed, ReferenceStatus.VALIDATED)  # no review record


def test_agent_cannot_be_the_reviewer() -> None:
    reviewed = promote(_proposed(), ReferenceStatus.REVIEWED)
    agent_review = ReviewRecord(reviewer="EvalGlass agent", decision="validated")
    with pytest.raises(ReferenceError, match="agent identity"):
        promote(reviewed, ReferenceStatus.VALIDATED, review=agent_review)


def test_author_cannot_self_validate() -> None:
    reviewed = promote(_proposed(), ReferenceStatus.REVIEWED)
    self_review = ReviewRecord("host:alice", "validated")  # same as the set's author
    with pytest.raises(ReferenceError, match="own validating reviewer"):
        promote(reviewed, ReferenceStatus.VALIDATED, review=self_review)


def test_host_reviewer_validates() -> None:
    reviewed = promote(_proposed(), ReferenceStatus.REVIEWED)
    validated = promote(
        reviewed, ReferenceStatus.VALIDATED, review=ReviewRecord("host:bob", "validated")
    )
    assert validated.status is ReferenceStatus.VALIDATED
    assert validated.review is not None
    assert validated.review.reviewer == "host:bob"


# --------------------------------------------------------------------------- #
# Status -> authority, comparability, evidence resolution, round-trip
# --------------------------------------------------------------------------- #


def test_proposed_maps_to_proposed_dataset_status() -> None:
    # A proposed reference cannot support a validated-dataset gate (reuses existing authority).
    assert dataset_status_for(ReferenceStatus.PROPOSED) is DatasetStatus.PROPOSED
    assert dataset_status_for(ReferenceStatus.VALIDATED) is DatasetStatus.VALIDATED


def test_content_change_breaks_comparability() -> None:
    a = _proposed()
    b = ReferenceSet(
        name=a.name,
        status=a.status,
        method=a.method,
        author=a.author,
        items=(
            *a.items[:0],
            type(a.items[0])(example_id="c1", value="different-gold"),
        ),
    )
    assert a.content_digest() != b.content_digest()


def test_evidence_resolution_flags_missing() -> None:
    ref_set = ReferenceSet(
        name="s",
        status=ReferenceStatus.PROPOSED,
        method="m",
        author="host:alice",
        items=(
            type(_proposed().items[0])(
                example_id="c1", value="gold", source_evidence_refs=("ev:1", "ev:missing")
            ),
        ),
    )
    diagnostics = validate_reference_set(ref_set, available_evidence=frozenset({"ev:1"}))
    assert any(d.code == "reference_evidence_unresolved" for d in diagnostics)


def test_round_trip() -> None:
    reviewed = promote(_proposed(), ReferenceStatus.REVIEWED)
    validated = promote(
        reviewed, ReferenceStatus.VALIDATED, review=ReviewRecord("host:bob", "validated", "ok")
    )
    back = ReferenceSet.from_dict(validated.to_dict())
    assert back.status is ReferenceStatus.VALIDATED
    assert back.review is not None
    assert back.review.reviewer == "host:bob"
    assert back.content_digest() == validated.content_digest()
