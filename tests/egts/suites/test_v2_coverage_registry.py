"""v2 coverage registry is complete and uses one honest id namespace (EG-AT6-10; plan §8.18).

Every v2 obligation has a row; executable scenario ids use the single ``m5c.*`` namespace; ``EG-V2``
is only the acceptance *checkpoint*, never a scenario id; deferred rows carry a reason and no
pretend scenario; and a ``covered`` row without a real scenario is an integrity violation.
"""

from __future__ import annotations

from pathlib import Path

from tests.egts.coverage_registry import (
    CoverageStatus,
    integrity_violations,
    load_registry,
    parse_registry,
)
from tests.egts.suites import M5C_SCENARIO_IDS

_COVERAGE = Path(__file__).resolve().parents[1] / "coverage" / "eg_m5c.yaml"

#: The full set of v2 obligations (the runner seam + the re-admitted/deferred capabilities).
_EXPECTED_TICKETS = {f"EG-M5C-{n}" for n in range(1, 9)}


def test_every_v2_obligation_has_exactly_one_row() -> None:
    registry = load_registry(_COVERAGE)
    tickets = [row.product_ticket for row in registry.rows]
    assert set(tickets) == _EXPECTED_TICKETS, (
        f"obligation rows drifted: {set(tickets) ^ _EXPECTED_TICKETS}"
    )
    assert len(tickets) == len(_EXPECTED_TICKETS), f"duplicate obligation row(s): {tickets}"


#: v2 obligations whose product surface is built and proven (each flips its row to ``covered`` with
#: a real ``m5c.*`` scenario). It grows as the hermetic tranche lands its lanes; every other row
#: must stay honestly ``not_started`` until its slice ships.
_BUILT_AND_COVERED = {
    "EG-M5C-1",  # EG-H0: the runner-attach seam
    "EG-M5C-2",  # EG-H2: hosted-dashboard ScoreSink
    "EG-M5C-3",  # EG-H2: prompt-optimizer handoff
    "EG-M5C-4",  # EG-H3: annotation foundation
    "EG-M5C-5",  # EG-H3: synthetic-data generator
    "EG-M5C-6",  # EG-R1/R2/R3 connectors + EG-R4 (proof suite + evidence pack + validator negctls)
    "EG-M5C-8",  # EG-H4: metrics explorer (read-only view)
}


def test_only_built_obligations_are_covered() -> None:
    """The registry stays honest: a built obligation is ``covered`` with a real scenario; every
    other row is ``not_started`` with no scenario, so pretend coverage cannot slip in."""
    registry = load_registry(_COVERAGE)
    for row in registry.rows:
        if row.product_ticket in _BUILT_AND_COVERED:
            assert row.status is CoverageStatus.COVERED, f"{row.product_ticket} should be covered"
            assert row.scenario_ids, f"{row.product_ticket}: a covered row needs a scenario id"
        else:
            assert row.status is CoverageStatus.NOT_STARTED, (
                f"{row.product_ticket} is covered but not in the built set"
            )
            assert not row.scenario_ids, (
                f"{row.product_ticket} names a scenario before one is built"
            )


def test_scenario_ids_use_only_the_m5c_namespace() -> None:
    registry = load_registry(_COVERAGE)
    for row in registry.rows:
        for scenario_id in row.scenario_ids:
            assert scenario_id.startswith("m5c."), (
                f"{row.product_ticket}: non-m5c id {scenario_id!r}"
            )
            assert not scenario_id.startswith("EG-V2"), "EG-V2 is a checkpoint, not a scenario id"


def test_every_covered_scenario_id_is_an_executed_m5c_scenario() -> None:
    """Defense-in-depth (mirrors the M0 guard): every scenario id a covered row cites must be drawn
    from the canonical M5C_SCENARIO_IDS inventory of ids the test_m5c_*_proof.py suites actually
    run. A typo'd or stale m5c.* id would satisfy the namespace shape check above while naming a
    scenario no suite executes — this catches that."""
    registry = load_registry(_COVERAGE)
    cited = {sid for row in registry.rows for sid in row.scenario_ids}
    unknown = sorted(cited - M5C_SCENARIO_IDS)
    assert not unknown, f"coverage cites id(s) absent from M5C_SCENARIO_IDS (typo?): {unknown}"


def test_m5c_scenario_inventory_has_no_unused_drift() -> None:
    """Reverse check: every id in the canonical inventory is actually cited by a covered row, so the
    inventory cannot silently accumulate dead ids that drift from what the registry proves."""
    registry = load_registry(_COVERAGE)
    cited = {sid for row in registry.rows for sid in row.scenario_ids}
    unused = sorted(M5C_SCENARIO_IDS - cited)
    assert not unused, f"M5C_SCENARIO_IDS has ids no covered row cites (dead inventory): {unused}"


def test_deferred_rows_carry_a_reason_and_no_pretend_scenario() -> None:
    registry = load_registry(_COVERAGE)
    for row in registry.rows:
        if row.status is CoverageStatus.NOT_STARTED:
            assert row.not_exercised_reason, f"{row.product_ticket}: deferred row needs a reason"
            assert row.not_exercised_reason.strip()
            assert not row.scenario_ids, f"{row.product_ticket}: a not-started row names a scenario"


def test_covered_without_a_scenario_is_an_integrity_violation() -> None:
    """Negative control: a 'covered' row with no scenario id is rejected (no pretend coverage)."""
    registry = parse_registry(
        {"rows": [{"product_ticket": "EG-X", "public_contract": "c", "status": "covered"}]}
    )
    assert integrity_violations(registry), (
        "a covered row without a scenario must be an integrity violation"
    )


def test_an_executable_row_would_use_m5c(tmp_path: Path) -> None:
    """Specificity: a covered row with a real m5c.* scenario is accepted and namespace-valid."""
    registry = parse_registry(
        {
            "rows": [
                {
                    "product_ticket": "EG-M5C-1",
                    "public_contract": "c",
                    "status": "covered",
                    "scenario_ids": ["m5c.runner_attach_seam"],
                }
            ]
        }
    )
    assert integrity_violations(registry) == []
    assert registry.rows[0].scenario_ids[0].startswith("m5c.")
