"""Scenario schema + validator (EGTS-M0-1).

A scenario declares, up front, what public contract is being proved and what
honest product output is expected (``test_architecture_build_contract.md §7``).
The validator rejects scenarios that omit the load-bearing expectations — that is
the EGTS-M0-1 negative control: *a scenario missing verdict, exit class,
authority, route, or coverage tags must fail validation* — so checker code can
never quietly carry an expectation that belonged in scenario data.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.egts.scenario import (
    AuthorityClaim,
    ExitClass,
    InputRoute,
    Milestone,
    ProductRing,
    Scenario,
    ScenarioError,
    Verdict,
    load_scenario,
    parse_scenario,
)


def _valid_scenario() -> dict[str, Any]:
    """A complete, valid scenario (mirrors the contract's worked example)."""
    return {
        "id": "m1.trace.local_jsonl.valid_call",
        "product_ticket": "EG-M1-3",
        "milestone": "M1",
        "product_ring": "Integration Layer",
        "public_contract": "TraceSource -> TraceEnvelope -> EvalUnit -> Example",
        "input_route": "trace_jsonl",
        "fixtures": {"trace": "traces/local_valid_call.jsonl"},
        "expect": {
            "verdict": "informational",
            "exit_class": "zero",
            "authority": "no_active_gate",
            "artifacts": {"scorecard": "required", "runrecord": "required"},
            "provenance": {"trace_source": "local_jsonl"},
        },
        "coverage_tags": ["contract.TraceEnvelope", "route.trace_jsonl", "ticket.EG-M1-3"],
    }


# --- sensitivity: a complete scenario parses into typed values --------------


def test_valid_scenario_parses() -> None:
    scenario = parse_scenario(_valid_scenario())
    assert isinstance(scenario, Scenario)
    assert scenario.id == "m1.trace.local_jsonl.valid_call"
    assert scenario.milestone is Milestone.M1
    assert scenario.product_ring is ProductRing.INTEGRATION_LAYER
    assert scenario.input_route is InputRoute.TRACE_JSONL
    assert scenario.expect.verdict is Verdict.INFORMATIONAL
    assert scenario.expect.exit_class is ExitClass.ZERO
    assert scenario.expect.authority is AuthorityClaim.NO_ACTIVE_GATE
    assert scenario.coverage_tags == [
        "contract.TraceEnvelope",
        "route.trace_jsonl",
        "ticket.EG-M1-3",
    ]


# --- the EGTS-M0-1 negative control -----------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        "id",
        "product_ticket",
        "milestone",
        "product_ring",
        "public_contract",
        "input_route",
        "fixtures",
        "coverage_tags",
        "expect",
    ],
)
def test_missing_top_level_field_fails(missing: str) -> None:
    data = _valid_scenario()
    del data[missing]
    with pytest.raises(ScenarioError) as exc:
        parse_scenario(data)
    assert missing in str(exc.value)


@pytest.mark.parametrize("missing", ["verdict", "exit_class", "authority", "artifacts"])
def test_missing_expect_field_fails(missing: str) -> None:
    data = _valid_scenario()
    del data["expect"][missing]
    with pytest.raises(ScenarioError) as exc:
        parse_scenario(data)
    assert missing in str(exc.value)


# --- enum / shape validation ------------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("milestone", "M9"),
        ("product_ring", "Nonsense Layer"),
        ("input_route", "carrier_pigeon"),
    ],
)
def test_unknown_top_level_enum_fails(field: str, bad: str) -> None:
    data = _valid_scenario()
    data[field] = bad
    with pytest.raises(ScenarioError):
        parse_scenario(data)


@pytest.mark.parametrize(
    ("field", "bad"),
    [("verdict", "green"), ("exit_class", "maybe"), ("authority", "vibes")],
)
def test_unknown_expect_enum_fails(field: str, bad: str) -> None:
    data = _valid_scenario()
    data["expect"][field] = bad
    with pytest.raises(ScenarioError):
        parse_scenario(data)


def test_empty_coverage_tags_fails() -> None:
    data = _valid_scenario()
    data["coverage_tags"] = []
    with pytest.raises(ScenarioError):
        parse_scenario(data)


def test_fixtures_must_be_a_mapping() -> None:
    data = _valid_scenario()
    data["fixtures"] = ["not", "a", "mapping"]
    with pytest.raises(ScenarioError):
        parse_scenario(data)


@pytest.mark.parametrize("bad_value", ["", None, 123, True])
def test_malformed_artifact_declaration_fails(bad_value: object) -> None:
    """expect.artifacts values must be non-empty strings — no silent str() coercion."""
    data = _valid_scenario()
    data["expect"]["artifacts"] = {"scorecard": bad_value}
    with pytest.raises(ScenarioError):
        parse_scenario(data)


def test_empty_coverage_tag_entry_fails() -> None:
    """A blank tag carries no coverage mapping — reject it."""
    data = _valid_scenario()
    data["coverage_tags"] = ["contract.TraceEnvelope", ""]
    with pytest.raises(ScenarioError):
        parse_scenario(data)


def test_non_mapping_scenario_fails() -> None:
    with pytest.raises(ScenarioError):
        parse_scenario(["not", "a", "scenario"])  # type: ignore[arg-type]


# --- YAML loading -----------------------------------------------------------


def test_load_scenario_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "scenario.yaml"
    path.write_text(
        textwrap.dedent("""
        id: m0.core.verdict.informational_no_gate
        product_ticket: EG-M0-5
        milestone: M0
        product_ring: Trust Layer
        public_contract: VerdictPayload
        input_route: core_in_memory
        fixtures:
          example: examples/no_gate.json
        expect:
          verdict: informational
          exit_class: zero
          authority: no_active_gate
          artifacts:
            scorecard: required
        coverage_tags:
          - contract.VerdictPayload
          - ticket.EG-M0-5
        """),
        encoding="utf-8",
    )
    scenario = load_scenario(path)
    assert scenario.milestone is Milestone.M0
    assert scenario.expect.verdict is Verdict.INFORMATIONAL
    assert scenario.product_ring is ProductRing.TRUST_LAYER


def test_load_invalid_yaml_scenario_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("id: x\nmilestone: M0\n", encoding="utf-8")  # missing most fields
    with pytest.raises(ScenarioError):
        load_scenario(path)
