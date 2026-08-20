"""Slice 2 (SG-P0-2): git diff pack builder tests.

Builds tiny throwaway git repos and asserts the diff pack captures
add/modify/delete/rename/binary/untracked/generated cases and changed-line
ranges deterministically; a missing base ref or non-git repo raises DiffError
(which the CLI maps to BLOCKED).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.diffpack import ChangedFile, DiffError, DiffPack, build_diff_pack


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "root")


def _commit_all(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    _init(r)
    return r


def _find(pack: DiffPack, path: str) -> ChangedFile | None:
    return next((f for f in pack.files if f.path == path), None)


def test_added_modified_deleted(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1\n")
    (repo / "b.py").write_text("y = 1\ny = 2\n")
    base = _commit_all(repo, "base")
    (repo / "a.py").write_text("x = 1\nx = 2\n")
    (repo / "b.py").unlink()
    (repo / "c.py").write_text("z = 1\n")
    _commit_all(repo, "head")
    pack = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    assert _find(pack, "a.py").change_type == "modified"  # type: ignore[union-attr]
    assert _find(pack, "b.py").change_type == "deleted"  # type: ignore[union-attr]
    assert _find(pack, "c.py").change_type == "added"  # type: ignore[union-attr]


def test_rename(repo: Path) -> None:
    (repo / "old.py").write_text("def f():\n    return 1\n" * 6)
    base = _commit_all(repo, "base")
    _git(repo, "mv", "old.py", "new.py")
    _commit_all(repo, "head")
    pack = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    f = _find(pack, "new.py")
    assert f is not None
    assert f.change_type == "renamed"
    assert f.old_path == "old.py"


def test_binary(repo: Path) -> None:
    (repo / "img.bin").write_bytes(bytes(range(256)) * 4)
    base = _commit_all(repo, "base")
    (repo / "img.bin").write_bytes(bytes(reversed(range(256))) * 4)
    _commit_all(repo, "head")
    pack = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    f = _find(pack, "img.bin")
    assert f is not None
    assert f.is_binary is True
    assert f.added_lines == ()


def test_changed_line_ranges(repo: Path) -> None:
    (repo / "m.py").write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
    base = _commit_all(repo, "base")
    lines = [f"line{i}" for i in range(1, 11)]
    lines[4] = "CHANGED"  # line 5 (1-based)
    (repo / "m.py").write_text("\n".join(lines) + "\n")
    _commit_all(repo, "head")
    pack = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    f = _find(pack, "m.py")
    assert f is not None
    assert any(start <= 5 < start + count for (start, count) in f.added_lines)


def test_untracked_included_when_flag_on(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "u.py").write_text("new = 1\n")
    pack = build_diff_pack(repo, base, "WORKTREE", include_untracked=True)
    f = _find(pack, "u.py")
    assert f is not None
    assert f.is_untracked is True
    assert f.change_type == "added"


def test_untracked_excluded_when_flag_off(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "u.py").write_text("new = 1\n")
    pack = build_diff_pack(repo, base, "WORKTREE", include_untracked=False)
    assert _find(pack, "u.py") is None


def test_generated_path_recorded_as_normal_change(repo: Path) -> None:
    (repo / "evals").mkdir()
    (repo / "evals" / "keep").write_text("x\n")
    base = _commit_all(repo, "base")
    (repo / "evals" / "baseline.json").write_text("{}\n")
    _commit_all(repo, "head")
    pack = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    f = _find(pack, "evals/baseline.json")
    assert f is not None
    assert f.change_type == "added"


def test_missing_base_ref_raises(repo: Path) -> None:
    with pytest.raises(DiffError):
        build_diff_pack(
            repo, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "HEAD", include_untracked=False
        )


def test_non_git_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(DiffError):
        build_diff_pack(tmp_path / "nope", "HEAD", "HEAD", include_untracked=False)


def test_ambiguous_ref_blocked(repo: Path) -> None:
    # A tag and a branch with the same name make "dup" ambiguous.
    _git(repo, "branch", "dup")
    _git(repo, "tag", "dup")
    with pytest.raises(DiffError):
        build_diff_pack(repo, "dup", "HEAD", include_untracked=False)


def test_untracked_symlink_recorded_without_crash(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "real.py").write_text("x = 1\n")
    (repo / "link.py").symlink_to("real.py")  # untracked symlink
    pack = build_diff_pack(repo, base, "WORKTREE", include_untracked=True)
    link = _find(pack, "link.py")
    assert link is not None
    assert link.is_untracked is True
    assert link.added_lines == ()


def test_determinism_and_sorted(repo: Path) -> None:
    (repo / "a.py").write_text("a = 1\n")
    (repo / "b.py").write_text("b = 1\n")
    base = _commit_all(repo, "base")
    (repo / "a.py").write_text("a = 2\n")
    (repo / "b.py").write_text("b = 2\n")
    _commit_all(repo, "head")
    p1 = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    p2 = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    assert p1 == p2
    paths = [f.path for f in p1.files]
    assert paths == sorted(paths)


def test_to_dict_json_round_trip(repo: Path) -> None:
    (repo / "a.py").write_text("a = 1\n")
    base = _commit_all(repo, "base")
    (repo / "a.py").write_text("a = 2\n")
    _commit_all(repo, "head")
    pack = build_diff_pack(repo, base, "HEAD", include_untracked=False)
    assert DiffPack.from_dict(pack.to_dict()) == pack
