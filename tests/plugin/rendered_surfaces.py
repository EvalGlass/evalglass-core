"""The committed user-facing prose surfaces the status/honesty guards scan (EG-AT3-4; §7.0).

One home for the audited-surface set so ST-CONSIST, ST-EXEC, and (later) the honesty audit
all scan the *same* files. ``docs/*.md`` / ``docs/*.html`` are intentionally excluded: the
internal design plans and the architecture map express status structurally (badges parsed by
the capability registry), not as user-facing prose. Test-only.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def audited_prose_files() -> list[Path]:
    """Committed user-facing prose: README/CHANGELOG/AGENTS, manifests, skills, plugin-docs."""
    paths: list[Path] = [
        _REPO / rel for rel in ("README.md", "CHANGELOG.md", "CITATION.cff", "AGENTS.md")
    ]
    paths += sorted((_REPO / ".claude-plugin").glob("*.json"))
    paths += sorted((_REPO / ".codex-plugin").glob("*.json"))
    paths += sorted((_REPO / "skills").glob("*/SKILL.md"))
    for sub in ("plugin-docs", "examples", "assets", "bin"):
        paths += sorted((_REPO / sub).rglob("*.md"))
    return [p for p in paths if p.is_file()]


def example_artifacts() -> list[Path]:
    """Committed example run artifacts (JSON reports) — checked for false execution evidence."""
    return sorted((_REPO / "examples").rglob("*.json"))


__all__ = ["audited_prose_files", "example_artifacts"]
