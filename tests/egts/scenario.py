"""EGTS scenario schema, declared-expectation model, and validator (EGTS-M0-1).

A *scenario* is the declarative unit of proof: it names the product ticket and
public contract under test, the input route, the fixtures, and — crucially — the
**declared** honest product output (verdict, exit class, authority claim,
required artifacts). EGTS compares product output to these declarations; it never
computes them (``test_architecture_build_contract.md §7``; ``tests/CLAUDE.md §2``).

The validator fails closed: a scenario missing a load-bearing expectation
(verdict, exit class, authority, route, or coverage tags) is rejected, so a
checker can never silently carry an expectation that belonged in scenario data.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


class ScenarioError(ValueError):
    """Raised when a scenario omits or misdeclares a required expectation."""


class Milestone(enum.StrEnum):
    M0 = "M0"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"
    M5 = "M5"


class ProductRing(enum.StrEnum):
    EVALUATION_SPINE = "Evaluation Spine"
    TRUST_LAYER = "Trust Layer"
    INTEGRATION_LAYER = "Integration Layer"
    ADOPTION_LAYER = "Adoption Layer"


class InputRoute(enum.StrEnum):
    CORE_IN_MEMORY = "core_in_memory"
    DATASET_JSONL = "dataset_jsonl"
    TRACE_JSONL = "trace_jsonl"
    OPEN_CONVENTION_TRACE = "open_convention_trace"
    SUBPROCESS_REPLAY = "subprocess_replay"
    SKILL_INSTALL = "skill_install"
    FAKE_JUDGE = "fake_judge"
    BASELINE = "baseline"
    SCORE_SINK = "score_sink"
    BACKEND_ADAPTER = "backend_adapter"
    RICHER_UNIT = "richer_unit"


class Verdict(enum.StrEnum):
    INFORMATIONAL = "informational"
    PASS = "pass"  # noqa: S105 — verdict enum value, not a credential
    FAIL = "fail"
    BLOCKED = "blocked"


class ExitClass(enum.StrEnum):
    ZERO = "zero"
    NONZERO_FAIL = "nonzero_fail"
    NONZERO_BLOCKED = "nonzero_blocked"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class AuthorityClaim(enum.StrEnum):
    NO_ACTIVE_GATE = "no_active_gate"
    ACTIVE_GATE = "active_gate"
    PROPOSED_DATA = "proposed_data"
    APPROVED_THRESHOLD = "approved_threshold"
    UNCALIBRATED_JUDGE = "uncalibrated_judge"
    CALIBRATED_JUDGE = "calibrated_judge"
    DRIFTED_JUDGE = "drifted_judge"
    POLICY_BLOCK = "policy_block"
    COMPARABLE_BASELINE = "comparable_baseline"
    NON_COMPARABLE_BASELINE = "non_comparable_baseline"


@dataclass(frozen=True)
class Expectation:
    """The declared honest product output for a scenario."""

    verdict: Verdict
    exit_class: ExitClass
    authority: AuthorityClaim
    artifacts: dict[str, str]
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    """A declarative proof obligation (``test_architecture_build_contract.md §7``)."""

    id: str
    product_ticket: str
    milestone: Milestone
    product_ring: ProductRing
    public_contract: str
    input_route: InputRoute
    fixtures: dict[str, Any]
    expect: Expectation
    coverage_tags: list[str]
    title: str | None = None
    egts_ticket: str | None = None
    negative_control: str | None = None
    optional_lane: str | None = None


def _require(data: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in data:
        raise ScenarioError(f"{ctx}: missing required field '{key}'")
    return data[key]


def _require_str(data: Mapping[str, Any], key: str, ctx: str) -> str:
    value = _require(data, key, ctx)
    if not isinstance(value, str) or not value:
        raise ScenarioError(f"{ctx}: field '{key}' must be a non-empty string, got {value!r}")
    return value


def _coerce_enum[E: enum.Enum](cls: type[E], value: Any, key: str, ctx: str) -> E:
    try:
        return cls(value)
    except ValueError:
        allowed = ", ".join(str(member.value) for member in cls)
        raise ScenarioError(
            f"{ctx}: field '{key}' has unknown value {value!r}; expected one of: {allowed}"
        ) from None


def _parse_expectation(data: Any, ctx: str) -> Expectation:
    if not isinstance(data, Mapping):
        raise ScenarioError(f"{ctx}: 'expect' must be a mapping, got {type(data).__name__}")
    artifacts = _require(data, "artifacts", ctx)
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ScenarioError(f"{ctx}: 'expect.artifacts' must be a non-empty mapping")
    clean_artifacts: dict[str, str] = {}
    for art_key, art_value in artifacts.items():
        if not isinstance(art_key, str) or not art_key:
            raise ScenarioError(f"{ctx}: 'expect.artifacts' has a non-string/empty key {art_key!r}")
        if not isinstance(art_value, str) or not art_value:
            raise ScenarioError(
                f"{ctx}: 'expect.artifacts[{art_key}]' must be a non-empty string; "
                f"got {art_value!r}"
            )
        clean_artifacts[art_key] = art_value
    provenance = data.get("provenance", {})
    if not isinstance(provenance, Mapping):
        raise ScenarioError(f"{ctx}: 'expect.provenance' must be a mapping when present")
    return Expectation(
        verdict=_coerce_enum(Verdict, _require(data, "verdict", ctx), "verdict", ctx),
        exit_class=_coerce_enum(ExitClass, _require(data, "exit_class", ctx), "exit_class", ctx),
        authority=_coerce_enum(AuthorityClaim, _require(data, "authority", ctx), "authority", ctx),
        artifacts=clean_artifacts,
        provenance=dict(provenance),
    )


def parse_scenario(data: Mapping[str, Any]) -> Scenario:
    """Validate a scenario mapping into a typed :class:`Scenario`, or raise."""
    if not isinstance(data, Mapping):
        raise ScenarioError(f"scenario must be a mapping, got {type(data).__name__}")

    scenario_id = _require_str(data, "id", "scenario")
    ctx = f"scenario {scenario_id!r}"

    fixtures = _require(data, "fixtures", ctx)
    if not isinstance(fixtures, Mapping):
        raise ScenarioError(f"{ctx}: 'fixtures' must be a mapping, got {type(fixtures).__name__}")

    coverage_tags = _require(data, "coverage_tags", ctx)
    if not isinstance(coverage_tags, list) or not coverage_tags:
        raise ScenarioError(f"{ctx}: 'coverage_tags' must be a non-empty list")
    if not all(isinstance(tag, str) and tag.strip() for tag in coverage_tags):
        raise ScenarioError(f"{ctx}: every entry in 'coverage_tags' must be a non-empty string")

    return Scenario(
        id=scenario_id,
        product_ticket=_require_str(data, "product_ticket", ctx),
        milestone=_coerce_enum(Milestone, _require(data, "milestone", ctx), "milestone", ctx),
        product_ring=_coerce_enum(
            ProductRing, _require(data, "product_ring", ctx), "product_ring", ctx
        ),
        public_contract=_require_str(data, "public_contract", ctx),
        input_route=_coerce_enum(
            InputRoute, _require(data, "input_route", ctx), "input_route", ctx
        ),
        fixtures=dict(fixtures),
        expect=_parse_expectation(_require(data, "expect", ctx), ctx),
        coverage_tags=list(coverage_tags),
        title=data.get("title"),
        egts_ticket=data.get("egts_ticket"),
        negative_control=data.get("negative_control"),
        optional_lane=data.get("optional_lane"),
    )


def load_scenario(path: Path | str) -> Scenario:
    """Load and validate a scenario from a YAML file."""
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return parse_scenario(data)
