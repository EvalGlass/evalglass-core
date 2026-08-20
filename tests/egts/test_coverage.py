"""Coverage registry + proof-planner foundation (EGTS-M0-2).

The coverage registry maps product tickets / architecture promises to the
scenarios that prove them, with an explicit status. Its job is to make *missing
proof a first-class result* (``tests/CLAUDE.md §14``): a product contract that
has no scenario and no explicit blocked/optional obligation is a coverage gap,
not a silent pass — that is the EGTS-M0-2 negative control.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.egts.coverage_registry import (
    CoverageError,
    CoverageRegistry,
    CoverageRow,
    CoverageStatus,
    find_gaps,
    integrity_violations,
    load_registry,
    parse_registry,
    plan_obligations,
)


def _row(**over: Any) -> dict[str, Any]:
    base = {
        "product_ticket": "EG-M0-1",
        "public_contract": "TraceEnvelope",
        "status": "covered",
        "scenario_ids": ["m0.contract.trace_envelope.roundtrip"],
        "required_command": "egts test-core",
    }
    base.update(over)
    return base


def _registry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"rows": rows}


def test_parse_valid_registry() -> None:
    reg = parse_registry(_registry([_row()]))
    assert isinstance(reg, CoverageRegistry)
    assert len(reg.rows) == 1
    row = reg.rows[0]
    assert isinstance(row, CoverageRow)
    assert row.product_ticket == "EG-M0-1"
    assert row.status is CoverageStatus.COVERED


# --- gap semantics ----------------------------------------------------------


def test_covered_with_scenarios_is_not_a_gap() -> None:
    reg = parse_registry(_registry([_row(status="covered")]))
    assert find_gaps(reg) == []


def test_not_started_requires_a_reason_then_is_accounted() -> None:
    """Alignment AT0 (EG-AT0-6): ``not_started`` needs a reason; then it is deferred-not-gap."""
    with pytest.raises(CoverageError, match="not_exercised_reason"):
        parse_registry(_registry([_row(status="not_started", scenario_ids=[])]))
    deferred = _row(status="not_started", scenario_ids=[], not_exercised_reason="deferred")
    reg = parse_registry(_registry([deferred]))
    assert find_gaps(reg) == []  # honestly deferred, not a silent gap


def test_partial_is_a_gap() -> None:
    reg = parse_registry(_registry([_row(status="partial")]))
    assert len(find_gaps(reg)) == 1


def test_blocked_is_not_a_gap() -> None:
    """An explicitly blocked obligation is accounted for, not a silent hole."""
    reg = parse_registry(_registry([_row(status="blocked", scenario_ids=[])]))
    assert find_gaps(reg) == []


def test_optional_is_not_a_gap() -> None:
    reg = parse_registry(_registry([_row(status="optional", scenario_ids=[])]))
    assert find_gaps(reg) == []


# --- the EGTS-M0-2 negative control -----------------------------------------


def test_contract_with_no_scenario_and_not_blocked_is_a_gap() -> None:
    """No scenario + no blocked/optional/deferred obligation must fail coverage."""
    reg = parse_registry(_registry([_row(status="partial", scenario_ids=[])]))
    gaps = find_gaps(reg)
    assert [g.public_contract for g in gaps] == ["TraceEnvelope"]


def test_covered_without_scenarios_is_an_integrity_violation() -> None:
    """Claiming 'covered' with no scenario is an overclaim — the worst kind of gap."""
    reg = parse_registry(_registry([_row(status="covered", scenario_ids=[])]))
    violations = integrity_violations(reg)
    assert len(violations) == 1
    assert violations[0] in find_gaps(reg)


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize("missing", ["product_ticket", "public_contract", "status"])
def test_missing_required_row_field_fails(missing: str) -> None:
    row = _row()
    del row[missing]
    with pytest.raises(CoverageError) as exc:
        parse_registry(_registry([row]))
    assert missing in str(exc.value)


def test_unknown_status_fails() -> None:
    with pytest.raises(CoverageError):
        parse_registry(_registry([_row(status="mostly_done")]))


def test_rows_must_be_present() -> None:
    with pytest.raises(CoverageError):
        parse_registry({"not_rows": []})


def test_empty_rows_fails() -> None:
    """An empty registry would let completeness checks pass with nothing proven."""
    with pytest.raises(CoverageError):
        parse_registry({"rows": []})


def test_blank_scenario_id_is_rejected() -> None:
    """A whitespace-only scenario id is not proof — reject it at parse time."""
    with pytest.raises(CoverageError):
        parse_registry(_registry([_row(status="covered", scenario_ids=["   "])]))


# --- proof planner foundation -----------------------------------------------


def test_plan_obligations_filters_by_milestone() -> None:
    reg = parse_registry(
        _registry(
            [
                _row(product_ticket="EG-M0-1", public_contract="TraceEnvelope"),
                _row(product_ticket="EG-M0-5", public_contract="VerdictPayload"),
                _row(product_ticket="EG-M1-3", public_contract="TraceSource"),
            ]
        )
    )
    planned = plan_obligations(reg, milestone="M0")
    assert {r.product_ticket for r in planned} == {"EG-M0-1", "EG-M0-5"}


def test_plan_obligations_filters_by_ticket() -> None:
    reg = parse_registry(
        _registry(
            [
                _row(product_ticket="EG-M0-1"),
                _row(product_ticket="EG-M0-5", public_contract="VerdictPayload"),
            ]
        )
    )
    planned = plan_obligations(reg, ticket="EG-M0-5")
    assert [r.product_ticket for r in planned] == ["EG-M0-5"]


# --- YAML loading + the shipped seed -----------------------------------------


def test_load_registry_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "coverage.yaml"
    path.write_text(
        textwrap.dedent("""
        rows:
          - product_ticket: EG-M0-5
            public_contract: VerdictPayload
            status: not_started
            scenario_ids: []
            not_exercised_reason: seed row for the loader round-trip test
            required_command: egts test-core
        """),
        encoding="utf-8",
    )
    reg = load_registry(path)
    assert reg.rows[0].status is CoverageStatus.NOT_STARTED


def test_shipped_eg_m0_seed_is_loadable_and_fully_covered() -> None:
    """The committed EG-M0 coverage seed parses and is fully covered by real scenarios."""
    seed = Path(__file__).parent / "coverage" / "eg_m0.yaml"
    reg = load_registry(seed)
    assert reg.rows, "EG-M0 seed must enumerate the milestone's obligations"
    assert all(r.product_ticket.startswith("EG-M0") for r in reg.rows)
    # Every EG-M0 obligation is now proven by an EGTS-M0 scenario — no gaps, no overclaim.
    assert find_gaps(reg) == []
    assert integrity_violations(reg) == []
    assert all(r.scenario_ids for r in reg.rows)
