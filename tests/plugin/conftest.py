"""Shared fixtures for the plugin-packaging test family (EGP-P0).

These tests assert *delivery/packaging* invariants (manifests, layout boundary, skill prose,
bootstrap behavior, migration). They touch no framework meaning. See ADR 0022 and
``docs/PLUGIN_TRANSFORMATION_PLAN.md`` §10.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

#: Repo root == plugin root (single-plugin marketplace, ADR 0022).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Plugin component directories that live at the plugin root and are NEVER vendored into a host.
PLUGIN_DIRS = (
    "skills",
    "hooks",
    "commands",
    "plugin-docs",
    "assets",
    "bin",
    ".claude-plugin",
    ".codex-plugin",
)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def _load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def plugin_manifest() -> dict[str, Any]:
    return _load_json(REPO_ROOT / ".claude-plugin" / "plugin.json")


@pytest.fixture
def marketplace_manifest() -> dict[str, Any]:
    return _load_json(REPO_ROOT / ".claude-plugin" / "marketplace.json")


@pytest.fixture
def codex_manifest() -> dict[str, Any]:
    """The Codex second-runtime manifest (P3; added in EGP-P3-1)."""
    return _load_json(REPO_ROOT / ".codex-plugin" / "plugin.json")


def skill_files() -> list[Path]:
    """Every shipped ``skills/<name>/SKILL.md``."""
    return sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
