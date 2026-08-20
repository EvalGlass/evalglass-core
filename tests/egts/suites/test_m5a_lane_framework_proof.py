"""EGTS-M5-1 — optional extension-lane framework proof (Integration Proof, Evidence Governance).

Proves the real product framework (``evalglass.harness.lanes``): lanes declare metadata, the
registry lists them WITHOUT importing any concrete lane, a lane result grants no authority, the
required tier does not statically import a lane, and a missing prerequisite skips. Each checker
family ships a negative control (``tests/CLAUDE.md §12``).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from evalglass.harness.lanes import (
    ExtensionLane,
    LanePort,
    LaneResult,
    LaneStatus,
    MissingPrerequisite,
    built_in_lanes,
)
from tests.egts.checkers import (
    CheckerError,
    check_lane_grants_no_authority,
    check_lane_imports_isolated,
    check_lane_metadata,
)

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"


# --- metadata declared -------------------------------------------------------


def test_m5a_lane_framework_metadata_declared() -> None:
    """m5a.lane_framework.metadata_declared — every declared lane states its full contract."""
    lanes = built_in_lanes().lanes()
    assert lanes, "no extension lanes declared"
    for lane in lanes:
        check_lane_metadata(lane)


def test_negctl_under_declared_lane_metadata_fails() -> None:
    class _UnderDeclared:
        name = "bad"
        purpose = "x"
        boundary = ""  # missing boundary statement
        deletion_rule = "y"
        module = "evalglass.adapters.judge_live"
        factory = "LiveJudgeModel"
        port = LanePort.JUDGE_MODEL

    with pytest.raises(CheckerError):
        check_lane_metadata(_UnderDeclared())


# --- registry lists without importing ---------------------------------------


def test_m5a_lane_framework_registry_lists_without_importing() -> None:
    """m5a.lane_framework.registry_lists_without_importing — listing imports no concrete lane.

    Run in a clean subprocess so prior in-process imports cannot mask a leak: build the registry,
    list every lane, and assert no lane's concrete module entered ``sys.modules``.
    """
    script = textwrap.dedent(
        """
        import sys
        from evalglass.harness.lanes import built_in_lanes
        reg = built_in_lanes()
        names = reg.names()
        modules = [lane.module for lane in reg.lanes()]
        leaked = [m for m in modules if m in sys.modules]
        assert names, "no lanes"
        assert not leaked, f"listing imported concrete lane(s): {leaked}"
        print("OK", names)
        """
    )
    proc = subprocess.run(  # noqa: S603 — fixed interpreter (sys.executable), in-repo script
        [sys.executable, "-c", script],
        cwd=str(_SRC.parents[1]),
        env={"PYTHONPATH": str(_SRC.parent), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.startswith("OK")


def test_m5a_resolve_is_the_only_import_path() -> None:
    """resolve() lazily imports the concrete lane (the metadata-only registry's escape hatch)."""
    factory = built_in_lanes().resolve("live-judge")
    assert factory.__name__ == "LiveJudgeModel"


# --- lane result grants no authority ----------------------------------------


def test_m5a_lane_result_grants_no_authority() -> None:
    """m5a.lane_framework.result_grants_no_authority — a LaneResult carries no verdict/authority."""
    result = LaneResult(lane="live-judge", status=LaneStatus.SKIPPED, report="no endpoint")
    check_lane_grants_no_authority(result)


def test_negctl_lane_result_with_verdict_fails() -> None:
    class _Authoritative:
        status = "ran"
        verdict = "pass"  # a lane must never carry a verdict

    with pytest.raises(CheckerError):
        check_lane_grants_no_authority(_Authoritative())


# --- required-tier import isolation (hermetic_import) -----------------------


def test_m5a_required_tier_import_isolated() -> None:
    """m5a.lane_framework.required_tier_import_isolated — no required module imports a lane."""
    for lane in built_in_lanes().lanes():
        check_lane_imports_isolated(_SRC, lane.module)


def test_negctl_required_module_importing_a_lane_fails(tmp_path: Path) -> None:
    # Build a fake src tree where a required-tier module imports the lane → must fail the checker.
    fake_src = tmp_path / "evalglass"
    (fake_src / "harness").mkdir(parents=True)
    (fake_src / "adapters").mkdir(parents=True)
    (fake_src / "adapters" / "judge_live.py").write_text("# the lane\n", encoding="utf-8")
    (fake_src / "harness" / "leaky.py").write_text(
        "from evalglass.adapters.judge_live import LiveJudgeModel\n", encoding="utf-8"
    )
    with pytest.raises(CheckerError):
        check_lane_imports_isolated(fake_src, "evalglass.adapters.judge_live")


# --- missing prerequisite skips ---------------------------------------------


def test_m5a_missing_prerequisite_skips_not_fails() -> None:
    """m5a.lane_framework.missing_prerequisite_skips — absent prereq raises MissingPrerequisite."""
    factory = built_in_lanes().resolve("live-judge")
    with pytest.raises(MissingPrerequisite):
        factory(endpoint=None)


def test_lane_from_dict_round_trip_is_stable() -> None:
    lane = ExtensionLane(
        name="x",
        purpose="p",
        port=LanePort.TRACE_SOURCE,
        module="a.b",
        factory="F",
        boundary="b",
        deletion_rule="d",
    )
    assert ExtensionLane.from_dict(lane.to_dict()) == lane
