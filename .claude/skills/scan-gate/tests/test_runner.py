"""Slice 10: detector orchestration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import runner
from scripts.detectors.base import DetectorResult
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import Policy, ProfileConfig, load_policy
from scripts.runner import run_detectors

SKILL_ROOT = Path(__file__).resolve().parent.parent
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


def _pack(*paths: str) -> DiffPack:
    files = tuple(
        ChangedFile(
            path=p,
            change_type="modified",
            old_path=None,
            is_binary=False,
            added_lines=((1, 1),),
            is_untracked=False,
        )
        for p in paths
    )
    return DiffPack(base_ref="b", head_ref="WORKTREE", files=files)


def test_runner_runs_all_profile_detectors_and_emits_ledger(tmp_path: Path) -> None:
    policy = load_policy(FAST_POLICY)
    findings, ledger, _blocked = run_detectors(_pack("README.md"), policy, tmp_path, "fast")
    tools = {e.tool for e in ledger}
    assert {
        "path_classifier",
        "imports_effects",
        "secrets",
        "generated_authority",
        "ci_script_guard",
        "manifest_drift",
    } <= tools
    assert findings == []


def test_runner_blocks_on_unimplemented_detector(tmp_path: Path) -> None:
    policy = Policy(
        version="t@1",
        profiles={
            "fast": ProfileConfig(
                name="fast", detectors=("path_classifier", "teleporter"), network="disabled"
            )
        },
        path_groups={"all": ("**",)},
        rules=(),
    )
    _, _, blocked = run_detectors(_pack("x.py"), policy, tmp_path, "fast")
    assert any("teleporter" in b for b in blocked)


def test_runner_converts_detector_crash_to_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_dp: object, _pol: object, _root: object) -> DetectorResult:
        raise RuntimeError("kaboom")

    monkeypatch.setitem(runner._REGISTRY, "path_classifier", boom)
    policy = Policy(
        version="t@1",
        profiles={
            "fast": ProfileConfig(name="fast", detectors=("path_classifier",), network="disabled")
        },
        path_groups={"all": ("**",)},
        rules=(),
    )
    _, ledger, blocked = run_detectors(_pack("x.py"), policy, tmp_path, "fast")
    assert any("crashed" in b for b in blocked)
    assert any(e.adapter_status == "error" for e in ledger)
