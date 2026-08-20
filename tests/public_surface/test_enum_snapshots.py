"""FS-SNAP-6 — freeze every live runtime enum; prove capability-status is disjoint (EG-AT1-3).

The typed contract is the spine. This guard freezes every ``Enum`` defined under
``evalglass.core`` / ``evalglass.harness`` (discovered, so a new enum cannot escape)
against a committed golden with **no additive-allow path**, and pins the three
doctrine facts the v2 status/ontology work must not blur:

* ``Verdict`` is exactly ``informational/pass/fail/blocked`` — ``infrastructure_error``
  is an ``ExitClass`` member, never a Verdict.
* ``AuthorityLevel`` is ``none/informational/gating`` — the resolution ladder
  ``informational/blocked/can_gate`` is ``ResolvedAuthority.level`` + two booleans, a
  different *type*, never an enum.
* the capability status ``now/next/planned/experimental`` is disjoint from every
  runtime outcome enum.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core.authority import AuthorityLevel, ResolvedAuthority
from evalglass.core.scores import ScoreStatus, Validity
from evalglass.core.verdict import Verdict
from evalglass.harness.exits import _VERDICT_CLASS, ExitClass, exit_code
from evalglass.harness.lanes import LaneStatus
from tests.plugin.status_registry import CapabilityStatus
from tests.public_surface._normalize import discover_runtime_enums, enum_members

_SNAP = Path(__file__).parent / "_snapshots"
_CAPABILITY_QUALNAME = "tests.plugin.status_registry.CapabilityStatus"


def _load(name: str) -> dict[str, Any]:
    data = json.loads((_SNAP / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _live_enum_map() -> dict[str, list[list[str]]]:
    """Discovered runtime enums + the test-only capability status, the full frozen set.

    Each enum is ``[name, value]`` pairs — names and values both frozen.
    """
    found = discover_runtime_enums()
    found[_CAPABILITY_QUALNAME] = enum_members(CapabilityStatus)
    return found


@pytest.mark.public_surface
def test_all_enum_members_match_golden() -> None:
    """Every runtime enum's members equal the golden — add/drop/reorder all fail."""
    assert _live_enum_map() == _load("enum_members.json")


@pytest.mark.public_surface
def test_verdict_exactly_four_no_infra() -> None:
    assert [v.value for v in Verdict] == ["informational", "pass", "fail", "blocked"]
    assert "infrastructure_error" not in {v.value for v in Verdict}


@pytest.mark.public_surface
def test_authoritylevel_three_not_ladder() -> None:
    assert [a.value for a in AuthorityLevel] == ["none", "informational", "gating"]
    assert {a.value for a in AuthorityLevel} != {"informational", "blocked", "can_gate"}


@pytest.mark.public_surface
def test_resolution_ladder_is_not_an_enum() -> None:
    """The ladder is a typed dataclass surface (level + booleans), never enum members."""
    ladder = {"informational", "blocked", "can_gate"}
    for pairs in discover_runtime_enums().values():
        assert {value for _, value in pairs} != ladder
    fields = {f.name for f in dataclasses.fields(ResolvedAuthority)}
    assert {"can_gate", "blocked", "level"} <= fields


@pytest.mark.public_surface
def test_exitclass_includes_infra_and_maps_to_2() -> None:
    """infrastructure_error lives in ExitClass (exit 2), and verdict→class covers all 4."""
    assert "infrastructure_error" in {e.value for e in ExitClass}
    assert exit_code(ExitClass.INFRASTRUCTURE_ERROR) == 2
    assert exit_code(ExitClass.ZERO) == 0
    assert set(_VERDICT_CLASS) == set(Verdict)


@pytest.mark.public_surface
def test_capability_status_disjoint_from_runtime_enums() -> None:
    capability = {m.value for m in CapabilityStatus}
    runtime: set[str] = set()
    for runtime_enum in (Verdict, ScoreStatus, Validity, AuthorityLevel, LaneStatus):
        runtime |= {m.value for m in runtime_enum}
    assert capability.isdisjoint(runtime)


@pytest.mark.public_surface
def test_sensitivity_added_enum_member_fails() -> None:
    """An added Verdict member drifts the golden — there is no additive-allow path."""
    tampered = copy.deepcopy(_live_enum_map())
    tampered["evalglass.core.verdict.Verdict"].append(["CERTIFIED", "certified"])
    assert tampered != _load("enum_members.json")


@pytest.mark.public_surface
def test_specificity_capability_status_once_with_four_values() -> None:
    """The one net-new enum is present exactly once with its conservative values."""
    golden = _load("enum_members.json")
    assert golden[_CAPABILITY_QUALNAME] == [
        ["NOW", "now"],
        ["NEXT", "next"],
        ["PLANNED", "planned"],
        ["EXPERIMENTAL", "experimental"],
    ]
