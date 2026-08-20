"""Layer-1 unit tests for the extension-lane framework (EG-M5-1; ADR 0017).

The framework is required-tier-safe: it declares lane *metadata* and a *result* shape, and a
metadata-only registry that lists lanes without importing any concrete lane module. A lane
grants no authority (its result carries no score/verdict/authority), a missing prerequisite
skips rather than fails, and schema-open metadata fails closed.
"""

from __future__ import annotations

import sys

import pytest

from evalglass.core import Diagnostic, Severity
from evalglass.harness.lanes import (
    ExtensionLane,
    LaneError,
    LanePort,
    LaneRegistry,
    LaneResult,
    LaneStatus,
    MissingPrerequisite,
    built_in_lanes,
)


def _lane(**over: object) -> ExtensionLane:
    base: dict[str, object] = {
        "name": "demo-lane",
        "purpose": "Demonstrate the lane contract.",
        "port": LanePort.TRACE_SOURCE,
        "module": "evalglass.adapters.judge_live",
        "factory": "LiveJudgeModel",
        "boundary": "Vendor objects normalized at the boundary; core never sees them.",
        "deletion_rule": "Deleting the lane leaves the local JSONL route intact.",
    }
    base.update(over)
    return ExtensionLane(**base)  # type: ignore[arg-type]


# --- ExtensionLane contract --------------------------------------------------


def test_lane_round_trips_through_dict() -> None:
    lane = _lane(optional_dependencies=("phoenix>=4",), prerequisites=("an endpoint",))
    assert ExtensionLane.from_dict(lane.to_dict()) == lane


def test_lane_to_dict_is_json_compatible() -> None:
    import json

    assert json.loads(json.dumps(_lane().to_dict()))["port"] == "trace_source"


@pytest.mark.parametrize(
    "field", ["name", "purpose", "module", "factory", "boundary", "deletion_rule"]
)
def test_empty_required_field_is_rejected(field: str) -> None:
    with pytest.raises(LaneError):
        _lane(**{field: ""})


def test_undotted_module_is_rejected() -> None:
    with pytest.raises(LaneError):
        _lane(module="notdotted")


def test_from_dict_missing_key_fails_closed() -> None:
    data = _lane().to_dict()
    del data["deletion_rule"]
    with pytest.raises(LaneError):
        ExtensionLane.from_dict(data)


def test_from_dict_unknown_port_fails_closed() -> None:
    data = _lane().to_dict()
    data["port"] = "not_a_port"
    with pytest.raises(LaneError):
        ExtensionLane.from_dict(data)


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(LaneError):
        ExtensionLane.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]


# --- LaneResult grants no authority -----------------------------------------


def test_lane_result_has_no_authority_bearing_field() -> None:
    result = LaneResult(lane="demo-lane", status=LaneStatus.RAN, report="ok")
    for forbidden in ("score", "scores", "verdict", "authority", "ci_should_fail"):
        assert not hasattr(result, forbidden), forbidden


def test_lane_result_round_trips() -> None:
    diag = Diagnostic(code="lane_skipped", severity=Severity.INFO, message="no endpoint")
    result = LaneResult(
        lane="demo-lane", status=LaneStatus.SKIPPED, report="skipped", diagnostics=[diag]
    )
    assert result.to_dict()["status"] == "skipped"
    assert result.to_dict()["diagnostics"][0]["code"] == "lane_skipped"


# --- LaneRegistry: metadata-only, lazy resolve ------------------------------


def test_registry_lists_and_gets() -> None:
    reg = LaneRegistry([_lane(name="a"), _lane(name="b")])
    assert reg.names() == ["a", "b"]
    assert reg.get("a").name == "a"


def test_registry_rejects_duplicate_name() -> None:
    with pytest.raises(LaneError):
        LaneRegistry([_lane(name="dup"), _lane(name="dup")])


def test_registry_unknown_lane_fails_closed() -> None:
    with pytest.raises(LaneError):
        LaneRegistry([_lane(name="a")]).get("missing")


def test_built_in_lanes_declares_live_judge_as_metadata() -> None:
    reg = built_in_lanes()
    assert "live-judge" in reg.names()
    lane = reg.get("live-judge")
    # Metadata only — the module is a string path, not an imported object.
    assert lane.module == "evalglass.adapters.judge_live"
    assert isinstance(lane.module, str)
    assert lane.deletion_rule
    assert lane.boundary


def test_resolve_lazily_imports_the_lane_factory() -> None:
    reg = built_in_lanes()
    factory = reg.resolve("live-judge")
    # resolve() is the only place the concrete lane is imported.
    assert factory.__name__ == "LiveJudgeModel"
    assert "evalglass.adapters.judge_live" in sys.modules


def test_resolve_unknown_module_fails_closed() -> None:
    reg = LaneRegistry([_lane(name="ghost", module="evalglass.adapters.does_not_exist")])
    with pytest.raises(LaneError):
        reg.resolve("ghost")


def test_resolve_missing_factory_fails_closed() -> None:
    reg = LaneRegistry(
        [_lane(name="nofac", module="evalglass.adapters.judge_live", factory="Nope")]
    )
    with pytest.raises(LaneError):
        reg.resolve("nofac")


def test_missing_prerequisite_is_a_runtime_error_not_value_error() -> None:
    # A missing prerequisite SKIPS/BLOCKS a run; it is never a structural LaneError.
    assert issubclass(MissingPrerequisite, RuntimeError)
    assert not issubclass(MissingPrerequisite, LaneError)
