"""Deterministic git diff pack for the scan-gate skill.

Builds a normalized, sorted record of the changed files (and changed-line
ranges) between a base ref and a head (a committish, or the working tree via
"WORKTREE"). This is the single source of "what changed" that every detector
consumes, so detectors never re-shell git themselves.

A missing/invalid base ref, an unreadable head, or a non-git repo raises
DiffError; the CLI maps that to a BLOCKED scan (missing proof, never PASS).
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - the scan-gate shells out to git to build the diff pack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_WORKTREE = {"", "WORKTREE", "WORKING_TREE", None}
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class DiffError(Exception):
    """Raised when the diff cannot be computed (missing ref, non-git repo)."""


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str
    change_type: str  # added | modified | deleted | renamed | copied | type_changed
    old_path: str | None
    is_binary: bool
    added_lines: tuple[tuple[int, int], ...]  # (start, count) ranges on the new side
    is_untracked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "change_type": self.change_type,
            "old_path": self.old_path,
            "is_binary": self.is_binary,
            "added_lines": [list(r) for r in self.added_lines],
            "is_untracked": self.is_untracked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangedFile:
        return cls(
            path=data["path"],
            change_type=data["change_type"],
            old_path=data.get("old_path"),
            is_binary=bool(data["is_binary"]),
            added_lines=tuple((int(a), int(b)) for a, b in data.get("added_lines", [])),
            is_untracked=bool(data.get("is_untracked", False)),
        )


@dataclass(frozen=True, slots=True)
class DiffPack:
    base_ref: str
    head_ref: str
    files: tuple[ChangedFile, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffPack:
        return cls(
            base_ref=data["base_ref"],
            head_ref=data["head_ref"],
            files=tuple(ChangedFile.from_dict(f) for f in data.get("files", [])),
        )


_STATUS_NAMES = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "T": "type_changed",
    "R": "renamed",
    "C": "copied",
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise DiffError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def _ensure_git_repo(repo: Path) -> None:
    if not repo.exists():
        raise DiffError(f"repo does not exist: {repo}")
    if _git(repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        raise DiffError(f"not a git repository: {repo}")


def _verify_commit(repo: Path, ref: str) -> None:
    # No --quiet: we need stderr to detect ambiguous refnames, which Git would
    # otherwise resolve by precedence and silently diff against the wrong object.
    proc = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", check=False)
    if proc.returncode != 0:
        raise DiffError(f"ref not found: {ref}")
    if "ambiguous" in proc.stderr.lower():
        raise DiffError(f"ambiguous ref: {ref}; use a fully-qualified ref (e.g. refs/heads/<name>)")


def _parse_name_status(raw: str) -> list[tuple[str, str, str | None]]:
    """Return (change_type, new_path, old_path) from `diff --name-status -z`."""
    tokens = [t for t in raw.split("\0") if t != ""]
    out: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(tokens):
        code = tokens[i]
        letter = code[0]
        if letter in ("R", "C"):
            old_path, new_path = tokens[i + 1], tokens[i + 2]
            out.append((_STATUS_NAMES[letter], new_path, old_path))
            i += 3
        else:
            path = tokens[i + 1]
            out.append((_STATUS_NAMES.get(letter, "modified"), path, None))
            i += 2
    return out


def _added_ranges(
    repo: Path, range_args: list[str], path: str
) -> tuple[bool, tuple[tuple[int, int], ...]]:
    """Return (is_binary, added-line ranges) for one path via a -U0 diff.

    --no-ext-diff / --no-textconv defeat configured external/textconv drivers so
    the parse sees raw, deterministic hunk headers (or "Binary files ... differ").
    A git failure raises DiffError -> BLOCKED rather than an incomplete pack.
    """
    proc = _git(
        repo,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "-M",
        "-U0",
        *range_args,
        "--",
        path,
    )
    text = proc.stdout
    if "Binary files" in text or "GIT binary patch" in text:
        return True, ()
    ranges: list[tuple[int, int]] = []
    for line in text.splitlines():
        m = _HUNK.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count > 0:
                ranges.append((start, count))
    return False, tuple(ranges)


def _untracked_files(repo: Path) -> list[str]:
    raw = _git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    return sorted(t for t in raw.split("\0") if t != "")


def _untracked_changed_file(repo: Path, path: str) -> ChangedFile:
    entry = repo / path
    # Never follow/read non-regular entries (symlink, FIFO, socket, broken link):
    # read_bytes() would follow or block. Record the path without scanning content.
    if entry.is_symlink() or not entry.is_file():
        return ChangedFile(
            path=path,
            change_type="added",
            old_path=None,
            is_binary=False,
            added_lines=(),
            is_untracked=True,
        )
    data = entry.read_bytes()
    is_binary = b"\0" in data
    added: tuple[tuple[int, int], ...] = ()
    if not is_binary and data:
        n = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
        added = ((1, n),) if n > 0 else ()
    return ChangedFile(
        path=path,
        change_type="added",
        old_path=None,
        is_binary=is_binary,
        added_lines=added,
        is_untracked=True,
    )


def build_diff_pack(
    repo_root: Path | str,
    base_ref: str,
    head_ref: str,
    *,
    include_untracked: bool,
) -> DiffPack:
    repo = Path(repo_root)
    _ensure_git_repo(repo)
    _verify_commit(repo, base_ref)

    is_worktree = head_ref in _WORKTREE
    if is_worktree:
        range_args = [base_ref]
    else:
        _verify_commit(repo, head_ref)
        range_args = [base_ref, head_ref]

    name_status = _git(repo, "diff", "--no-color", "-M", "--name-status", "-z", *range_args).stdout
    files: list[ChangedFile] = []
    for change_type, new_path, old_path in _parse_name_status(name_status):
        if change_type == "deleted":
            files.append(
                ChangedFile(
                    path=new_path,
                    change_type=change_type,
                    old_path=old_path,
                    is_binary=False,
                    added_lines=(),
                    is_untracked=False,
                )
            )
            continue
        is_binary, ranges = _added_ranges(repo, range_args, new_path)
        files.append(
            ChangedFile(
                path=new_path,
                change_type=change_type,
                old_path=old_path,
                is_binary=is_binary,
                added_lines=ranges,
                is_untracked=False,
            )
        )

    if include_untracked and is_worktree:
        tracked = {f.path for f in files}
        for path in _untracked_files(repo):
            if path not in tracked:
                files.append(_untracked_changed_file(repo, path))

    files.sort(key=lambda f: f.path)
    head_label = "WORKTREE" if is_worktree else head_ref
    return DiffPack(base_ref=base_ref, head_ref=head_label, files=tuple(files))
