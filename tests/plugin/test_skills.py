"""EGP-P0-4/5/6 + honesty-audit gate: skill frontmatter, no authority verbs, honest prose.

These assert the *delivery* invariants the plan makes structural (PLUGIN_TRANSFORMATION_PLAN.md
§2c, §4.4, §9.9, §10): every SKILL.md is well-formed and portable; the surface ships no
authority-claiming verb; the always-on honesty skill carries its guardrail; and no plugin prose
overclaims (the embryo of the fail-closed honesty-audit CI gate).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from tests.plugin.conftest import REPO_ROOT, skill_files

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: §9.9 — the plugin ships no command/verb that claims authority or "makes it pass".
_AUTHORITY_VERBS = ("gate", "approve", "certify", "verify", "validate", "score", "pass")
_AUTHORITY_VERB_RE = re.compile(
    r"/evalglass\s+(?:" + "|".join(_AUTHORITY_VERBS) + r")\b", re.IGNORECASE
)

#: Overclaim phrases that may never appear as a positive claim in any rendered plugin prose.
_OVERCLAIM = (
    "production-certified",
    "battle-tested",
    "guarantees correctness",
    "guarantee of correctness",
    "proof of correctness",
    "trusted by",
    "production-ready",
)

#: A line that *prohibits* an overclaim legitimately names it; exempt clear negations.
_PROHIBITION = re.compile(
    r"never|not |n't|forbid|avoid|do not|must not|rather than|instead of|❌|evidence, not proof",
    re.IGNORECASE,
)


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    assert m, f"{path} is missing a YAML frontmatter block"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"{path} frontmatter must be a mapping"
    return data


def test_skills_present() -> None:
    names = {p.parent.name for p in skill_files()}
    expected = {
        "evalglass",
        "evalglass-honesty",
        "evaluate-an-agentic-app",
        "installing-evalglass",
        "reading-a-scorecard",
    }
    assert expected <= names, f"missing v1 skills: {expected - names}"


@pytest.mark.parametrize("skill", skill_files(), ids=lambda p: p.parent.name)
def test_frontmatter_name_and_description(skill: Path) -> None:
    fm = _frontmatter(skill)
    name = fm.get("name")
    desc = fm.get("description")
    assert isinstance(name, str), f"{skill}: name must be a string"
    assert _KEBAB.match(name), f"{skill}: name must be kebab-case"
    assert name == skill.parent.name, f"{skill}: frontmatter name must equal directory name"
    assert isinstance(desc, str), f"{skill}: description must be a string"
    assert len(desc.strip()) >= 40, f"{skill}: description too thin to trigger"


def test_no_authority_verb_anywhere() -> None:
    """No skill routes a /evalglass gate|approve|certify|verify|validate|score|pass verb."""
    for skill in skill_files():
        text = skill.read_text(encoding="utf-8")
        hit = _AUTHORITY_VERB_RE.search(text)
        assert hit is None, f"{skill}: authority-claiming verb in surface: {hit.group(0)!r}"


def test_honesty_skill_carries_its_guardrail() -> None:
    text = (REPO_ROOT / "skills" / "evalglass-honesty" / "SKILL.md").read_text(encoding="utf-8")
    low = " ".join(text.lower().split())  # normalize wrapping so phrase checks aren't brittle
    assert "informational" in low
    # It must explicitly forbid calling a non-failing run "passing".
    assert re.search(r"never[^.\n]*pass", low), "honesty skill must forbid 'passing' wording"
    assert "evidence, not proof" in low
    fm = _frontmatter(REPO_ROOT / "skills" / "evalglass-honesty" / "SKILL.md")
    assert (
        "report" in str(fm["description"]).lower() or "interpret" in str(fm["description"]).lower()
    )


def test_no_overclaim_in_plugin_prose() -> None:
    """Honesty audit (embryo): no positive overclaim in any rendered plugin prose."""
    targets: list[Path] = list(skill_files())
    targets += [REPO_ROOT / "hooks" / "session-start.sh"]
    for sub in ("bin", "plugin-docs", "assets"):
        targets += sorted((REPO_ROOT / sub).glob("*.md"))
    violations: list[str] = []
    for path in targets:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if _PROHIBITION.search(line):
                continue
            for phrase in _OVERCLAIM:
                if phrase in low:
                    violations.append(f"{path}:{i}: {phrase!r} :: {line.strip()}")
    assert not violations, "overclaiming plugin prose:\n" + "\n".join(violations)
