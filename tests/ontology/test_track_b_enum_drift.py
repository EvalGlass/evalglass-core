"""Track B — code↔ontology enum drift is now STRICT (EG-AT5-3 / EG-H1; §D 6C; ADR 0032).

After the EG-H1 reconciliation the ontology mirrors the live enums: ``enum.authority`` models
``AuthorityLevel`` (``none``/``informational``/``gating``) — the ``informational``/``blocked``/
``can_gate`` resolution ladder is a separate concept, not enum members; ``enum.data-policy`` has
all five members; ``enum.exit-class`` models the ``ExitClass`` names; and ``ThresholdApproval`` /
``JudgeCalibration`` / ``LanePort`` / ``LaneStatus`` / ``Maturity`` are now modeled entities. The
``expected_enum_drift.json`` manifest is therefore **empty**, and the guard is green only when the
produced drift is exactly empty.

Per-enum negative controls (always run) prove the detector still fires on a dropped or phantom
member, so strict equality has teeth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.ontology.enum_drift import (
    compute_enum_drift,
    enum_member_drift,
    extract_enum_members,
    live_member_values,
)
from tests.ontology.ontology_loader import Ontology

pytestmark = pytest.mark.ontology

_MANIFEST = Path(__file__).resolve().parent / "expected_enum_drift.json"


def _expected() -> list[dict[str, object]]:
    data: list[dict[str, object]] = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return data


# --- whole-artifact reconciliation (skip-with-count when unavailable) -------
def test_enum_drift_matches_expected_manifest(real_ontology: Ontology) -> None:
    drift = compute_enum_drift(extract_enum_members(real_ontology))
    assert drift == _expected()


def test_authority_is_reconciled_to_authority_level(real_ontology: Ontology) -> None:
    """``enum.authority`` now models the live ``AuthorityLevel`` members exactly (no drift)."""
    members = extract_enum_members(real_ontology)
    assert members["enum.authority"] == live_member_values("AuthorityLevel")
    assert members["enum.authority"] == {"none", "informational", "gating"}
    assert enum_member_drift("enum.authority", members["enum.authority"]) is None


def test_data_policy_exit_class_and_formerly_missing_enums_are_modeled(
    real_ontology: Ontology,
) -> None:
    members = extract_enum_members(real_ontology)
    assert members["enum.data-policy"] == live_member_values("DataPolicy")
    assert members["enum.exit-class"] == live_member_values("ExitClass")
    # The five formerly-missing enums are now modeled entities with their live members.
    for ont_id, live in (
        ("enum.threshold-approval", "ThresholdApproval"),
        ("enum.judge-calibration", "JudgeCalibration"),
        ("enum.lane-port", "LanePort"),
        ("enum.lane-status", "LaneStatus"),
        ("enum.maturity", "Maturity"),
    ):
        assert members[ont_id] == live_member_values(live)
        assert enum_member_drift(ont_id, members[ont_id]) is None


def test_manifest_is_empty_strict_mode() -> None:
    """Strict mode: the expected-drift manifest is empty — the ontology mirrors the live enums."""
    assert _expected() == []


# --- per-enum detector negatives (always run) -------------------------------
def test_matching_verdict_members_is_no_drift() -> None:
    assert enum_member_drift("enum.verdict", live_member_values("Verdict")) is None


def test_dropping_a_verdict_member_is_drift() -> None:
    members = live_member_values("Verdict") - {"blocked"}
    record = enum_member_drift("enum.verdict", members)
    assert record is not None
    assert record["live_only"] == ["blocked"]


def test_adding_a_phantom_verdict_member_is_drift() -> None:
    members = live_member_values("Verdict") | {"warn"}
    record = enum_member_drift("enum.verdict", members)
    assert record is not None
    assert record["ontology_only"] == ["warn"]


def test_doctored_ontology_breaks_manifest_equality(real_ontology: Ontology) -> None:
    """Sensitivity: perturbing a clean enum makes the whole-artifact drift diverge from manifest."""
    members = extract_enum_members(real_ontology)
    members["enum.verdict"] = members["enum.verdict"] - {"blocked"}
    assert compute_enum_drift(members) != _expected()
