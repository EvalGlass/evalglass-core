"""EGTS-M5-7 (M5a scope) — verify-deletion: every optional lane is removable.

The defining M5 invariant (build contract §6/§8; EG-M5 epic): **removing every optional lane leaves
M1-M4 required proof green, and no optional dependency is reachable from a required path.**
This suite proves it concretely — it copies the source tree, physically deletes every declared lane
file, and confirms the required tier (core / harness / required adapters) still imports — plus the
static import-graph scan and a lane-failure-cannot-mask control.

Run via ``egts verify-deletion``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from evalglass.harness.lanes import LaneResult, LaneStatus, built_in_lanes
from tests.egts.checkers import (
    CheckerError,
    check_lane_grants_no_authority,
    check_lane_imports_isolated,
)

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"


def test_m5a_every_lane_is_import_isolated() -> None:
    """m5a.deletion.required_tier_imports_no_lane — static: no required module imports a lane."""
    for lane in built_in_lanes().lanes():
        check_lane_imports_isolated(_SRC, lane.module)


def test_m5a_deleting_all_lanes_leaves_required_tier_importable(tmp_path: Path) -> None:
    """m5a.deletion.required_imports_with_lanes_removed — delete lanes; required still imports."""
    pkg = tmp_path / "evalglass"
    shutil.copytree(_SRC, pkg)
    deleted: list[str] = []
    for lane in built_in_lanes().lanes():
        lane_file = pkg.parent / (lane.module.replace(".", "/") + ".py")
        if lane_file.is_file():
            lane_file.unlink()
            deleted.append(lane.module)
    assert deleted, "no lane files were deleted"

    # Required-tier imports must still succeed with every lane file gone. The framework itself
    # (harness.lanes) still imports — its registry holds metadata strings, not lane imports.
    script = textwrap.dedent(
        """
        import evalglass.core
        import evalglass.harness.cli
        import evalglass.harness.runner
        import evalglass.harness.lanes
        import evalglass.adapters.dataset_jsonl
        import evalglass.adapters.trace_jsonl
        import evalglass.adapters.trace_open_convention
        print("OK")
        """
    )
    proc = subprocess.run(  # noqa: S603 — fixed interpreter (sys.executable), in-repo script
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={"PYTHONPATH": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"required tier failed to import with lanes deleted: {proc.stderr!r}"
    )
    assert proc.stdout.strip() == "OK"


def test_m5a_resolving_a_deleted_lane_fails_closed(tmp_path: Path) -> None:
    """A deleted lane cannot be resolved — the framework fails closed, not a ghost import."""
    pkg = tmp_path / "evalglass"
    shutil.copytree(_SRC, pkg)
    (pkg / "adapters" / "score_sink_export.py").unlink()
    script = textwrap.dedent(
        """
        from evalglass.harness.lanes import built_in_lanes, LaneError
        try:
            built_in_lanes().resolve("score-sink-export")
        except LaneError:
            print("OK")
        else:
            print("FAIL: resolved a deleted lane")
        """
    )
    proc = subprocess.run(  # noqa: S603 — fixed interpreter, in-repo script
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={"PYTHONPATH": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.stdout.strip() == "OK", f"stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_m5a_lane_failure_cannot_mask_a_required_result() -> None:
    """m5a.deletion.lane_failure_cannot_mask — a lane result is never a required pass/verdict."""
    # A failing lane is a LaneResult (blocked + diagnostic), which grants no authority and so can
    # neither mark a required run green nor change its verdict.
    failed = LaneResult(lane="x", status=LaneStatus.BLOCKED, report="boom")
    check_lane_grants_no_authority(failed)
    assert failed.status is not LaneStatus.RAN


def test_negctl_required_module_importing_a_lane_fails(tmp_path: Path) -> None:
    fake_src = tmp_path / "evalglass"
    (fake_src / "harness").mkdir(parents=True)
    (fake_src / "adapters").mkdir(parents=True)
    (fake_src / "adapters" / "score_sink_export.py").write_text("# lane\n", encoding="utf-8")
    (fake_src / "harness" / "leaky.py").write_text(
        "from evalglass.adapters.score_sink_export import FileScorecardExportSink\n",
        encoding="utf-8",
    )
    with pytest.raises(CheckerError):
        check_lane_imports_isolated(fake_src, "evalglass.adapters.score_sink_export")
