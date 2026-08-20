"""Shared detector primitives: result shape and a deterministic glob matcher.

The glob matcher implements gitignore-ish `**` semantics (match across path
segments) so policy path globs like "src/evalglass/core/**", "**/baselines/**",
and "**/*.sh" behave predictably and identically everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from scripts.contracts import Finding, ToolLedgerEntry


@dataclass
class DetectorResult:
    findings: list[Finding] = field(default_factory=list)
    ledger: list[ToolLedgerEntry] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)


@lru_cache(maxsize=1024)
def _compiled(glob: str) -> re.Pattern[str]:
    parts: list[str] = []
    i, n = 0, len(glob)
    while i < n:
        if glob[i : i + 3] == "**/":
            parts.append("(?:.*/)?")  # zero or more leading path segments
            i += 3
        elif glob[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif glob[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def path_matches(path: str, glob: str) -> bool:
    return _compiled(glob).match(path) is not None


def match_groups(path: str, path_groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Return every path-group name whose globs match *path* (sorted)."""
    matched = [
        name for name, globs in path_groups.items() if any(path_matches(path, g) for g in globs)
    ]
    return tuple(sorted(matched))
