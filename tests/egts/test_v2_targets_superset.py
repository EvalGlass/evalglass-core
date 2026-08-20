"""FS-EGTS — keep the M0-M5 proofs honest + add the v2 m5c coverage home (EG-AT1 Slice 7, EG-AT1-7).

The existing milestone proof suites stay green (run in the suite); this guard keeps the
coverage registries honest as v2 extends them: no existing scenario id is dropped (a
frozen floor), no existing obligation is overclaimed, and the new ``eg_m5c.yaml`` ships
*empty-but-honest* — every deferred v2 capability is ``not_started`` with a stated
reason, so it reads as "NOT EXERCISED", never a silent gap. A lane row becomes
``covered`` only when a real m5c.* scenario backs it (AT4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.egts.coverage_registry import (
    CoverageError,
    CoverageStatus,
    find_gaps,
    integrity_violations,
    load_registry,
    parse_registry,
)
from tests.egts.suites import M0_SCENARIO_IDS

_EGTS = Path(__file__).resolve().parent
_COVERAGE = _EGTS / "coverage"
_SNAP = _EGTS / "_snapshots"
_EXISTING = ("eg_m0", "eg_m1", "eg_m2", "eg_m3", "eg_m4", "eg_m5a", "eg_m5b")


def _load(name: str) -> object:
    return load_registry(_COVERAGE / f"{name}.yaml")


def _all_registry_scenario_ids() -> set[str]:
    ids: set[str] = set()
    for name in _EXISTING:
        for row in load_registry(_COVERAGE / f"{name}.yaml").rows:
            ids.update(row.scenario_ids)
    return ids


def _covered_tickets() -> set[str]:
    """Product tickets the existing M0-M5 registries currently mark ``covered``."""
    tickets: set[str] = set()
    for name in _EXISTING:
        for row in load_registry(_COVERAGE / f"{name}.yaml").rows:
            if row.status is CoverageStatus.COVERED:
                tickets.add(row.product_ticket)
    return tickets


def _m5c_tickets() -> set[str]:
    return {row.product_ticket for row in load_registry(_COVERAGE / "eg_m5c.yaml").rows}


def test_milestone_proof_suites_present() -> None:
    """A representative M0-M5 proof/acceptance suite from each milestone still exists."""
    suites = _EGTS / "suites"
    for name in (
        "test_m0_core_proof",
        "test_m1_acceptance",
        "test_m2_trust_runtime_proof",
        "test_m3_skill_proof",
        "test_m4_judge_proof",
        "test_m5a_deletion_proof",
        "test_m5b_acceptance",
    ):
        assert (suites / f"{name}.py").is_file(), f"missing milestone proof suite: {name}"


def test_existing_registries_have_no_integrity_violations() -> None:
    """No existing M0-M5 obligation claims 'covered' without a backing scenario."""
    for name in _EXISTING:
        assert integrity_violations(load_registry(_COVERAGE / f"{name}.yaml")) == []


def test_egts_targets_are_superset() -> None:
    """v2 may ADD a scenario id, never DROP one — the frozen floor stays covered."""
    golden = json.loads((_SNAP / "egts_targets.json").read_text(encoding="utf-8"))
    assert set(M0_SCENARIO_IDS) >= set(golden["m0_scenario_ids"])
    assert _all_registry_scenario_ids() >= set(golden["registry_scenario_ids"])


def test_accepted_obligations_stay_covered() -> None:
    """An obligation that was 'covered' must STAY covered — a downgrade to blocked /
    optional / not_started (even keeping its scenario id) drops it from this floor."""
    golden = json.loads((_SNAP / "egts_targets.json").read_text(encoding="utf-8"))
    missing = set(golden["covered_tickets"]) - _covered_tickets()
    assert not missing, f"accepted obligations silently stopped being covered: {sorted(missing)}"


def test_m5c_roster_is_a_floor() -> None:
    """No deferred v2 capability may silently disappear from the coverage home — every
    frozen EG-M5C ticket must still be present (it may become covered, never vanish)."""
    golden = json.loads((_SNAP / "egts_targets.json").read_text(encoding="utf-8"))
    missing = set(golden["m5c_tickets"]) - _m5c_tickets()
    assert not missing, f"a deferred m5c capability was dropped from the roster: {sorted(missing)}"


def test_eg_m5c_rows_are_honestly_accounted() -> None:
    registry = load_registry(_COVERAGE / "eg_m5c.yaml")
    assert registry.rows, "the m5c registry must enumerate the v2 obligations"
    for row in registry.rows:
        if row.status is CoverageStatus.COVERED:
            assert row.scenario_ids, f"{row.product_ticket}: a covered row needs a scenario"
        else:
            assert row.status is CoverageStatus.NOT_STARTED
            assert row.not_exercised_reason, f"{row.product_ticket}: deferred row needs a reason"
            assert not row.scenario_ids, (
                f"{row.product_ticket}: a not-exercised row has no scenario"
            )
    # Every row is accounted (covered-with-scenario OR not_started-with-reason), so it is neither a
    # gap nor an integrity violation: `egts coverage` over m5c is honestly green.
    assert find_gaps(registry) == []
    assert integrity_violations(registry) == []


def test_built_m5c_obligations_are_covered_with_scenarios() -> None:
    """The runner-attach seam (EG-M5C-1) is built (EG-H0), so its row is covered with a real
    m5c.* scenario; remaining deferred capabilities stay not_started until their slice ships."""
    rows = {row.product_ticket: row for row in load_registry(_COVERAGE / "eg_m5c.yaml").rows}
    seam = rows["EG-M5C-1"]
    assert seam.status is CoverageStatus.COVERED
    assert seam.scenario_ids == ["m5c.runner_attach_seam"]


def test_sensitivity_covered_row_without_scenario_is_overclaim() -> None:
    registry = parse_registry(
        {"rows": [{"product_ticket": "EG-X", "public_contract": "c", "status": "covered"}]}
    )
    assert integrity_violations(registry), "a covered row with no scenario must be an overclaim"


def test_specificity_not_started_requires_reason() -> None:
    with pytest.raises(CoverageError):
        parse_registry(
            {"rows": [{"product_ticket": "EG-X", "public_contract": "c", "status": "not_started"}]}
        )
    accounted = parse_registry(
        {
            "rows": [
                {
                    "product_ticket": "EG-X",
                    "public_contract": "c",
                    "status": "not_started",
                    "not_exercised_reason": "not built; no required path loads it",
                }
            ]
        }
    )
    assert find_gaps(accounted) == []  # a stated reason makes it accounted, not a gap
