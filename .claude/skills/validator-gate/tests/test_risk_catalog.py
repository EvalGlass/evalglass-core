"""Slice 5 (VG-P1-7): risk-catalog guard.

The 11 APPENDIX_RISK_CATALOG entries are optional supporting metadata, never
family ids. This proves the canonical set is present and that the family/risk
distinction is correct — including the deliberate overlap where
``authority_verdict`` is both a family id and a risk ref (so it is a valid
family selection), while a pure risk ref like ``report_public_surface`` is not.
"""

from __future__ import annotations

from scripts.contracts import FamilyId
from scripts.risk_catalog import RISK_REFS, is_family_id, is_risk_ref


def test_canonical_eleven_risk_refs() -> None:
    assert (
        frozenset(
            {
                "contract_architecture",
                "scenario_expectation",
                "hermetic_required_tier",
                "authority_verdict",
                "provenance_baseline",
                "runtime_input_routes",
                "skill_vendoring",
                "judge_rag_data_policy",
                "optional_lanes_deletion",
                "report_public_surface",
                "ci_execution",
            }
        )
        == RISK_REFS
    )


def test_family_ids_are_recognized() -> None:
    for f in FamilyId:
        assert is_family_id(f.value)


def test_pure_risk_ref_is_not_a_family_id() -> None:
    assert is_risk_ref("report_public_surface")
    assert not is_family_id("report_public_surface")


def test_authority_verdict_is_both_family_and_risk_ref() -> None:
    # Deliberate overlap: a valid family selection AND a catalog entry.
    assert is_family_id("authority_verdict")
    assert is_risk_ref("authority_verdict")


def test_unknown_token_is_neither() -> None:
    assert not is_family_id("vibes_check")
    assert not is_risk_ref("vibes_check")
