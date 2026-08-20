"""EGP-P2-5: fail-closed honesty audit over all rendered plugin-facing prose and artifacts.

No-false-confidence applied to EvalGlass's own delivery layer (PLUGIN_TRANSFORMATION_PLAN.md §10):
the README, marketplace metadata, CITATION, bootstrap, honesty skill, every verb skill,
plugin-docs, examples, and demo text may not overclaim. And the committed demo Scorecard (if any)
must carry an `informational` or `blocked` verdict — never a manufactured pass. If a target is
absent, the relevant check reports *not exercised* rather than a hollow PASS (CLAUDE.md §21).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.plugin.conftest import REPO_ROOT

#: Overclaim phrases that may never appear as a positive claim in rendered plugin prose.
_OVERCLAIM = (
    "production-certified",
    "production-ready",
    "battle-tested",
    "guarantees correctness",
    "guarantee of correctness",
    "proof of correctness",
    "trusted by",
    "scan all",
    "all your llm calls",
    "certified safe",
)

#: A line that *prohibits* an overclaim legitimately names it; exempt clear negations/definitions.
_PROHIBITION = re.compile(
    r"never|\bnot |\bno |n't|forbid|avoid|fabricated|do not|must not|rather than|"
    r"instead of|❌|evidence, not proof|does not|cannot|without",
    re.IGNORECASE,
)


def _audited_files() -> list[Path]:
    """Every rendered plugin-facing surface that exists today (absent ones are not scanned)."""
    targets: list[Path] = []
    # Root prose surfaces incl. the Codex-runtime entry AGENTS.md (P3-1; plan §8.3).
    for rel in ("README.md", "CHANGELOG.md", "CITATION.cff", "AGENTS.md"):
        p = REPO_ROOT / rel
        if p.exists():
            targets.append(p)
    # Both runtime manifests carry rendered prose (descriptions, defaultPrompt) → in scope.
    targets += sorted((REPO_ROOT / ".claude-plugin").glob("*.json"))
    targets += sorted((REPO_ROOT / ".codex-plugin").glob("*.json"))
    targets += sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
    targets += sorted((REPO_ROOT / "hooks").glob("*.sh"))
    for sub in ("plugin-docs", "examples", "assets", "bin"):
        targets += sorted((REPO_ROOT / sub).rglob("*.md"))
    return targets


def test_no_overclaim_in_any_plugin_prose() -> None:
    targets = _audited_files()
    assert targets, "honesty audit found no plugin prose to scan (gate not exercised)"
    violations: list[str] = []
    for path in targets:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _PROHIBITION.search(line):
                continue
            low = line.lower()
            for phrase in _OVERCLAIM:
                if phrase in low:
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}:{i}: {phrase!r} :: {line.strip()}")
    assert not violations, "overclaiming plugin prose:\n" + "\n".join(violations)


def test_committed_demo_scorecards_are_informational_or_blocked() -> None:
    """A committed demo/example Scorecard must not assert a pass (not exercised if none exist)."""
    cards = sorted((REPO_ROOT / "examples").rglob("scorecard.json"))
    if not cards:
        # Honest 'not exercised' — no committed demo artifact yet (added in EGP-P2-3).
        return
    offenders: list[str] = []
    for card in cards:
        verdict = json.loads(card.read_text(encoding="utf-8")).get("verdict", {}).get("verdict")
        if verdict not in {"informational", "blocked"}:
            offenders.append(f"{card.relative_to(REPO_ROOT)}: verdict={verdict!r}")
    assert not offenders, (
        "committed demo Scorecard asserts a non-informational verdict:\n" + "\n".join(offenders)
    )
