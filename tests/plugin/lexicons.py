"""Shared status/honesty lexicons (EG-AT3-3+; alignment plan §7.0 P1-3).

One module owns the deny/allow lexicons and the deferred-capability keyword set, so
the production assertions and every negative control read the *same* words — inline
lexicon literals in an ``ST-*`` test are forbidden. The deferred-capability keywords
are anchored to the HTML-derived capability registry (a test proves each keyword maps
to a non-``now`` registry alias), so this list cannot silently diverge from the map.

Test-only data; never imported by ``src/evalglass/**``.
"""

from __future__ import annotations

import re

from tests.plugin.status_registry import CapabilityStatus

#: The four capability-status words.
STATUS_WORDS = frozenset({"now", "next", "planned", "experimental"})

#: Phrases that honestly qualify a capability as not-shipped / optional / future. A deferred
#: capability mentioned in prose must carry one of these (or a non-``now`` status word) so it is
#: never shown as if it ships today.
FUTURE_MARKERS = frozenset(
    {
        "next",
        "planned",
        "experimental",
        "coming",
        "soon",
        "will ",
        "roadmap",
        "future",
        "later",
        "upcoming",
        "deferred",
        "unbuilt",
        "not built",
        "not yet",
        "not available",
        "not shipped",
        "not in 0.1",
        "design note",
        "opt-in",
        "optional",
        "stub",
        "placeholder",
    }
)

#: Phrases asserting a capability is shipped / running *now*. Deliberately specific (not bare
#: "shipped", which appears in honest negations like "no provider SDK shipped").
NOW_MARKERS = frozenset(
    {
        "available now",
        "ships today",
        "shipped now",
        "runs today",
        "running today",
        "is live now",
        "live today",
    }
)

#: Distinctive deferred-capability keywords → the capability status the architecture map assigns.
#: Anchored to ``CAPABILITY_REGISTRY`` by ``test_deferred_keywords_match_registry``.
DEFERRED_CAPABILITY_KEYWORDS: dict[str, CapabilityStatus] = {
    "hosted dashboard": CapabilityStatus.NEXT,
    "dashboard sink": CapabilityStatus.NEXT,
    "prompt-optimizer": CapabilityStatus.NEXT,
    "optimizer handoff": CapabilityStatus.NEXT,
    "synthetic-data generation": CapabilityStatus.PLANNED,
    "langfuse": CapabilityStatus.PLANNED,
    "phoenix": CapabilityStatus.PLANNED,
    "langsmith": CapabilityStatus.PLANNED,
    "metrics explorer": CapabilityStatus.PLANNED,
    "per-source-function": CapabilityStatus.PLANNED,
    "annotation workflow": CapabilityStatus.EXPERIMENTAL,
    "scorecard export": CapabilityStatus.EXPERIMENTAL,
    "live-judge": CapabilityStatus.EXPERIMENTAL,
}

#: Words that negate a status claim ("not available now"), so a now-phrase in their wake is
#: not a now-claim. Distinct from a future marker about a *different* capability in the sentence.
NEGATORS = frozenset({"not ", "no longer", "never ", "isn't", "aren't", "won't", "cannot"})

#: Banned architecture terms — the product says "Evaluation Core" / "effect-free core" (§7.3).
BANNED_ARCHITECTURE_TERMS = frozenset({"test kernel", "pure kernel", "kernel"})

#: Run-outcome subjects a capability-status word must never modify (§7.5 ST-NOTVERDICT-2). Bare
#: "scorecard" is intentionally excluded — "scorecard export" is itself a capability.
RUN_OUTCOME_TERMS = frozenset({"run", "verdict", "result"})

#: Capability subjects a *verdict* word must never label (the reverse ST-NOTVERDICT-2 direction).
CAPABILITY_SUBJECT_TERMS = frozenset(
    {"lane", "capability", "extension", "connector", "sink", "feature"}
)

#: Verdict words that can never describe a *capability* ("the lane is fail"). ``blocked`` and
#: ``informational`` are excluded — a lane is legitimately ``blocked`` (LaneStatus) and authority is
#: legitimately ``informational``.
VERDICT_LABEL_WORDS = frozenset({"pass", "fail", "passed", "failed"})

#: Unearned-success vocabulary that must never be applied to a run/result/release without an
#: evidence-not-proof prohibition (§7.3 ST-VOCAB-3).
UNEARNED_SUCCESS_WORDS = frozenset(
    {"production-ready", "proof of correctness", "certified", "certify", "guaranteed"}
)

#: Authority verbs the coding-agent command surface must never expose (host-owned only).
BANNED_AUTHORITY_VERBS = frozenset({"approve", "certify", "gate "})

#: Platform / hosted / telemetry / guarantee connotations the quality-control framing must not
#: carry without an evidence-not-proof prohibition (§7.4 ST-POSN-2, GAP-12).
PLATFORM_CONNOTATION = frozenset(
    {
        "hosted platform",
        "provider key",
        "api key",
        "telemetry",
        "dashboard service",
        "guarantee",
        "guarantees",
        "assures",
        "certifies quality",
    }
)

#: Evidence-not-proof prohibitions that make an otherwise-strong sentence honest.
EVIDENCE_PROHIBITION = frozenset(
    {
        "evidence, not",
        "not proof",
        "no false",
        "honestly supports",
        "only what",
        "bounded",
        "not a guarantee",
        "does not",
        "never",
        "host-owned",
        "you approve",
        "you own",
    }
)

#: Stale phrasings that wrongly present ``view --by-call`` as unavailable (§7.3 ST-VOCAB-5).
#: ``--by-call`` ships now (F1 landed); current surfaces must not say it is gated/deferred/declines.
BY_CALL_STALE_PATTERNS = frozenset(
    {
        "not in 0.1",
        "not available",
        "waits on f1",
        "gated on f1",
        "gated on framework",
        "blocked until f1",
        "deferred to f1",
        "declines, pointing at f1",
        "by-call declines",
        "by-call is absent",
        "by-call is unbuilt",
        "by-call is planned",
        "by-call is deferred",
    }
)

#: Canonical product terms that must remain present across the surfaces (§7.3 ST-VOCAB-4).
CANONICAL_TERMS = frozenset(
    {
        "quality-control",
        "coding agent",
        "scorecard",
        "host-owned",
        "authority",
        "runrecord",
    }
)


#: Present-tense execution verbs that describe a capability *running now* (alignment plan §7.2).
#: Stems carry their own ``\w*`` so inflections are caught: single-word verbs match "pulls" /
#: "uploads" / "generates" / "queries"; the multi-word forms match "exports to" / "pushes to" /
#: "connects to" (the inflection sits on the verb, not after "to").
_EXECUTION_VERB_RE = re.compile(
    r"\b(?:pull|upload|generat|quer|tune|fetch|sync|stream)\w*"
    r"|\b(?:export|push|connect)\w*\s+to\b",
    re.IGNORECASE,
)


def has_future_marker(line: str) -> bool:
    """True if ``line`` carries any honest not-now qualifier (case-insensitive)."""
    lowered = line.lower()
    return any(marker in lowered for marker in FUTURE_MARKERS)


def has_execution_verb(text: str) -> bool:
    """True if ``text`` describes a capability *executing* now (a present-tense run verb)."""
    return bool(_EXECUTION_VERB_RE.search(text))


def deferred_keywords_in(line: str) -> list[str]:
    """The deferred-capability keywords mentioned in ``line`` (case-insensitive)."""
    lowered = line.lower()
    return [kw for kw in DEFERRED_CAPABILITY_KEYWORDS if kw in lowered]


__all__ = [
    "BANNED_ARCHITECTURE_TERMS",
    "BANNED_AUTHORITY_VERBS",
    "BY_CALL_STALE_PATTERNS",
    "CANONICAL_TERMS",
    "DEFERRED_CAPABILITY_KEYWORDS",
    "EVIDENCE_PROHIBITION",
    "FUTURE_MARKERS",
    "NEGATORS",
    "NOW_MARKERS",
    "PLATFORM_CONNOTATION",
    "STATUS_WORDS",
    "UNEARNED_SUCCESS_WORDS",
    "deferred_keywords_in",
    "has_execution_verb",
    "has_future_marker",
]
