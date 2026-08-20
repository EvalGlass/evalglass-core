"""Shared markdown prose-scanning primitives for the status/honesty guards (EG-AT3-4).

One home for the block-joining + sentence-splitting logic the ST-CONSIST and ST-EXEC
scanners share, so a capability-status guard cannot quietly drift from a sibling guard.
Test-only; never imported by ``src/evalglass/**``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

from tests.plugin.lexicons import (
    BANNED_ARCHITECTURE_TERMS,
    EVIDENCE_PROHIBITION,
    PLATFORM_CONNOTATION,
    UNEARNED_SUCCESS_WORDS,
    deferred_keywords_in,
)

_BULLET = re.compile(r"^\s{0,3}([-*]|\d+\.)\s|^#")
_QUALITY_CONTROL = re.compile(r"quality[ -]control", re.IGNORECASE)


def is_prohibition(text: str) -> bool:
    """True if ``text`` is itself a prohibition that names a banned term in order to forbid it."""
    lowered = text.lower()
    return any(
        token in lowered for token in ("banned", "instead", "never use", "do not use", "say ")
    )


def violates_platform_connotation(sentence: str) -> bool:
    """ST-POSN-2: a quality-control sentence carrying a platform / guarantee connotation with no
    evidence-not-proof prohibition. The single detector both the production guard and its
    sensitivity control share."""
    lowered = sentence.lower()
    return bool(
        _QUALITY_CONTROL.search(lowered)
        and any(c in lowered for c in PLATFORM_CONNOTATION)
        and not any(p in lowered for p in EVIDENCE_PROHIBITION)
    )


def has_banned_architecture_term(block: str) -> bool:
    """ST-VOCAB-2: a block using a banned architecture term (kernel/…) outside a prohibition."""
    lowered = block.lower()
    return any(term in lowered for term in BANNED_ARCHITECTURE_TERMS) and not is_prohibition(block)


def violates_unearned_success(sentence: str) -> bool:
    """ST-VOCAB-3: an unearned-success word with no evidence-not-proof prohibition present."""
    lowered = sentence.lower()
    return any(word in lowered for word in UNEARNED_SUCCESS_WORDS) and not any(
        p in lowered for p in EVIDENCE_PROHIBITION
    )


def logical_blocks(text: str) -> list[tuple[int, str]]:
    """Group wrapped markdown lines into ``(start_line, joined_text)`` units.

    A new block begins at a blank line or a bullet/heading marker; wrapped continuation lines are
    joined so a qualifier on a bullet's second line still qualifies a capability named on its first.
    """
    out: list[tuple[int, str]] = []
    start = 0
    buf: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            if buf:
                out.append((start, " ".join(buf)))
                buf = []
            continue
        if _BULLET.match(line) and buf:
            out.append((start, " ".join(buf)))
            buf = []
        if not buf:
            start = lineno
        buf.append(line)
    if buf:
        out.append((start, " ".join(buf)))
    return out


def scan_capability_sentences(paths: Iterable[Path], violates: Callable[[str], bool]) -> list[str]:
    """``"<file>:<line>:<keyword>"`` for every sentence naming a deferred capability that violates.

    Sentence granularity over joined blocks: a qualifier on a bullet's wrapped line still counts,
    but one qualified sentence cannot bless an unrelated bare mention in the same bullet.
    """
    findings: list[str] = []
    for path in paths:
        for start, block in logical_blocks(path.read_text(encoding="utf-8")):
            for sentence in re.split(r"[.;!]\s", block):
                keywords = deferred_keywords_in(sentence)
                if keywords and violates(sentence):
                    findings.append(f"{path.name}:{start}:{keywords[0]}")
    return findings


__all__ = [
    "has_banned_architecture_term",
    "is_prohibition",
    "logical_blocks",
    "scan_capability_sentences",
    "violates_platform_connotation",
    "violates_unearned_success",
]
