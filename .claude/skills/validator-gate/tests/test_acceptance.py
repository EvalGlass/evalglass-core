"""Slice 13: Layer-2 acceptance gate — the assembled Validator Gate, end to end.

This is the completion gate. It proves the assembled gate cannot quietly
overclaim: the five families are all wired, malformed/ambiguous input fails
closed before any family validation, an unvalidated claim never PASSes, and the
fail-closed precedence holds through the real product path (``run_adapter``).
"""

from __future__ import annotations

import pytest

from scripts.adapter import run_adapter
from scripts.contracts import FamilyId, Status
from scripts.runner import FAMILY_REGISTRY


def _pack(**over) -> dict:
    base = {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-13.acceptance",
        "source_boundary": {"product": ["sc"]},
        "claims": [
            {
                "id": "c1",
                "text": "report matches verdict",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc"],
            }
        ],
        "artifacts": [
            {
                "id": "sc",
                "kind": "scorecard",
                "authority": "product",
                "content": {"verdict": "pass"},
            }
        ],
    }
    base.update(over)
    return base


def test_all_five_families_are_registered() -> None:
    assert set(FAMILY_REGISTRY) == set(FamilyId)


# Malformed / ambiguous packs must fail closed (BLOCKED) before family validation.
MALFORMED = {
    "bad_schema_version": {**_pack(), "schema_version": "validator.evidence.v9"},
    "non_object_scan_result": {**_pack(), "scan_gate_result": "PASS"},
    "string_boundary_bucket": {**_pack(), "source_boundary": {"product": "sc"}},
    "missing_source_boundary": {**_pack(), "source_boundary": {}},
    "invalid_gate_plan_family": {**_pack(), "gate_plan": {"families": ["vibes_check"]}},
}


@pytest.mark.parametrize("name", list(MALFORMED))
def test_malformed_input_blocks(name: str) -> None:
    result, _ = run_adapter(MALFORMED[name])
    assert result.status is Status.BLOCKED, name


def test_unvalidated_claim_never_passes() -> None:
    # A claim with nothing to route from cannot be validated -> BLOCKED, not PASS.
    result, _ = run_adapter(
        _pack(claims=[{"id": "c1", "text": "unroutable", "required_artifacts": ["sc"]}])
    )
    assert result.status is Status.BLOCKED


def test_clean_authority_claim_passes() -> None:
    # The happy path still works end to end.
    result, _ = run_adapter(_pack())
    assert result.status is Status.PASS
    assert result.claims_validated == ["c1"]


def test_fail_outranks_block_across_claims() -> None:
    # One claim proves a violation (FAIL), another is blocked: overall FAIL.
    pack = _pack(
        source_boundary={"product": ["sc"], "external_contracts": ["rep"]},
        claims=[
            {
                "id": "ok-overclaim",
                "text": "report overclaims",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc2", "rep"],
            },
            {
                "id": "blocked-claim",
                "text": "needs an absent artifact",
                "expected_families": ["contract_boundary"],
                "required_artifacts": ["absent"],
            },
        ],
        artifacts=[
            {
                "id": "sc2",
                "kind": "scorecard",
                "authority": "product",
                "content": {"verdict": "blocked"},
            },
            {
                "id": "rep",
                "kind": "report",
                "authority": "external",
                "content": {"claimed_status": "pass"},
            },
        ],
    )
    # fix boundary to include sc2
    pack["source_boundary"] = {"product": ["sc2"], "external_contracts": ["rep"]}
    result, _ = run_adapter(pack)
    assert result.status is Status.FAIL  # FAIL outranks the BLOCKED claim
