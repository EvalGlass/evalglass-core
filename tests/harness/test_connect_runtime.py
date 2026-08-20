"""`connect --live` runtime invariants (EG-P2-2): clean-skip, egress fail-closed, import boundary.

Proves the scaffolded lane behaves honestly when a subsequent ``run`` executes it: a missing
prerequisite is a clean ``SKIPPED`` (never a crash), the default ``unknown`` data policy blocks
egress before any provider call (fully hermetic — no SDK touched), and the verb code statically
imports no connector lane module (the SDK stays off every required path).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from evalglass.core import Verdict
from evalglass.harness import connect
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.lanes import LaneStatus, MissingPrerequisite, built_in_lanes
from evalglass.harness.runner import run_config

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"


def _metric() -> dict[str, object]:
    return {
        "name": "field_presence",
        "evaluator_ref": "field_presence@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0, 1],
    }


def _cfg_with_lane(lane: dict[str, object]) -> RuntimeConfig:
    return RuntimeConfig.from_mapping({"metrics": [_metric()], "lanes": [lane]})


def test_connect_verb_statically_imports_no_lane_module() -> None:
    """The verb writes config only — it imports no connector lane module (SDK off every path)."""
    lane_modules = {lane.module for lane in built_in_lanes().lanes()}
    tree = ast.parse((_SRC / "harness" / "connect.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not (imported & lane_modules), (
        f"connect.py imports lane module(s): {imported & lane_modules}"
    )


def test_scaffolded_lane_egress_forbidden_blocks_hermetically(tmp_path: Path) -> None:
    """EG-P2-2: the default ``unknown`` policy refuses egress BEFORE any client call (no SDK)."""
    lane = connect.connector_lane_config("langfuse", endpoint="https://lf.example")
    assert lane["data_policy"] == "unknown"  # fail-closed default
    record = run_config(_cfg_with_lane(lane), root=tmp_path)
    # The lane ran through the seam but its egress was refused → BLOCKED side channel, no network.
    statuses = {lr["lane"]: lr["status"] for lr in record.lane_results}
    assert statuses["langfuse-trace"] == LaneStatus.BLOCKED.value
    # A lane never touches the verdict: the run stays honestly informational.
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL


def test_scaffolded_lane_missing_prerequisite_is_clean_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EG-P2-2: a missing extra/credential ⇒ ``SKIPPED`` (clean); the run still scores."""
    from evalglass.adapters import trace_langfuse

    def _absent(self: object) -> dict[str, object]:
        raise MissingPrerequisite("the langfuse-trace extra is not installed")

    monkeypatch.setattr(trace_langfuse.LangfuseTraceSource, "_default_fetch", _absent)
    # data_policy=permitted so egress is allowed and the (patched) fetch is reached.
    lane = connect.connector_lane_config(
        "langfuse", endpoint="https://lf.example", data_policy="permitted"
    )
    record = run_config(_cfg_with_lane(lane), root=tmp_path)
    statuses = {lr["lane"]: lr["status"] for lr in record.lane_results}
    assert statuses["langfuse-trace"] == LaneStatus.SKIPPED.value  # clean skip, never a crash
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
