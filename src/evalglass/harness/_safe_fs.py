"""Shared fail-closed write-path helpers for governed harness surfaces (EG-H3).

The synthetic generator and the annotation foundation both write local artifacts under the host
root and must refuse the same unsafe shapes — an unsafe name, a symlinked path component, or a
destination escaping the root. Factoring the rules here keeps every governed write surface
consistent (and avoids the per-surface drift the optimizer/synthetic Codex passes flagged).

Stdlib-only; raises :class:`~evalglass.harness.governance.GovernanceError` so a refusal is a clean,
typed governance error, never a crash mid-write.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from evalglass.harness.governance import GovernanceError


def safe_name(name: str, *, kind: str = "name") -> str:
    """Return ``name`` if it is a single plain filename stem; else refuse (no path / traversal)."""
    if not name or not name.strip():
        raise GovernanceError(f"{kind} must be a non-empty string")
    if "/" in name or "\\" in name or name in {".", ".."} or name != Path(name).name:
        raise GovernanceError(f"{kind} must be a plain filename stem, got {name!r}")
    return name


def refuse_symlinks(root: Path, relative_parts: Sequence[str]) -> None:
    """Refuse if any existing component of ``root/relative_parts`` is a symlink (fail-closed).

    ``mkdir``/``write_text`` would follow a symlinked directory or pre-planted output file and
    clobber a target outside the intended tree; refusing first keeps the write inside the root.
    """
    probe = root
    for part in relative_parts:
        probe = probe / part
        if probe.is_symlink():
            raise GovernanceError(f"refusing to write through a symlink: {probe}")


def assert_within_root(root: Path, path: Path) -> None:
    """Defense in depth: refuse if ``path`` resolves outside ``root`` (e.g. a symlinked root)."""
    if not path.resolve().is_relative_to(root.resolve()):
        raise GovernanceError(f"path escapes the host root: {path}")


def checked_target(base: Path, candidate: Path, *, what: str) -> Path:
    """Validate a host-supplied (e.g. CLI-argument) file path before a read/write, fail-closed.

    Resolves ``candidate`` (collapsing any ``..`` and following symlinks) and confines the result
    under ``base`` so a traversal — or a symlink redirecting outside the intended tree — cannot
    escape it; a symlinked final component is refused outright. Returns the safe, resolved path, so
    the caller reads/writes exactly the path that was validated. ``candidate`` is the fully-formed
    target (the caller joins it under the intended directory before calling).
    """
    base_resolved = base.resolve()
    resolved = candidate.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise GovernanceError(f"{what} escapes {base}: {candidate}")
    if candidate.is_symlink():
        raise GovernanceError(f"refusing to use a symlinked {what}: {candidate}")
    return resolved
