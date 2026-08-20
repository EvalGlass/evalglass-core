"""Risk-catalog guard (VG-P1-7).

The 11 APPENDIX_RISK_CATALOG entries are optional supporting metadata for a
selected family — they can inform a finding's `risk_ref`, but they can never be
selected as family ids, run as a gate, or create a status. This module is the
single source of that distinction, used by the router to reject a gate plan that
names a risk-catalog ref where a family id is required.

Note the deliberate overlap: ``authority_verdict`` is both a canonical family id
and a catalog entry, so it is a valid family selection; the other ten entries
are not family ids.
"""

from __future__ import annotations

from scripts.contracts import FamilyId

RISK_REFS: frozenset[str] = frozenset(
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

_FAMILY_VALUES: frozenset[str] = frozenset(f.value for f in FamilyId)


def is_family_id(token: str) -> bool:
    return token in _FAMILY_VALUES


def is_risk_ref(token: str) -> bool:
    return token in RISK_REFS
