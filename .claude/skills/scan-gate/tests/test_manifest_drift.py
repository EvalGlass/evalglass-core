"""Slice 10: manifest drift detector tests (WARN, incl. deletions)."""

from __future__ import annotations

from pathlib import Path

from scripts.detectors import manifest_drift
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


def _run(path: str, change_type: str) -> manifest_drift.DetectorResult:
    pack = DiffPack(
        base_ref="b",
        head_ref="WORKTREE",
        files=(
            ChangedFile(
                path=path,
                change_type=change_type,
                old_path=None,
                is_binary=False,
                added_lines=((1, 1),),
                is_untracked=False,
            ),
        ),
    )
    return manifest_drift.run(pack, load_policy(FAST_POLICY), Path("."))


def test_modified_manifest_warns() -> None:
    result = _run("pyproject.toml", "modified")
    assert {f.rule_id for f in result.findings} == {"manifest.review_required"}
    assert all(f.severity.value == "warn" for f in result.findings)


def test_deleted_manifest_warns() -> None:
    result = _run("uv.lock", "deleted")
    assert "manifest.review_required" in {f.rule_id for f in result.findings}


def test_deleted_dockerfile_warns() -> None:
    result = _run("docker/Dockerfile", "deleted")
    assert "manifest.review_required" in {f.rule_id for f in result.findings}


def test_non_manifest_ignored() -> None:
    result = _run("src/evalglass/core/x.py", "modified")
    assert result.findings == []
