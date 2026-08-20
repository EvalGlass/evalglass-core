"""Slice 0: prove the skill harness and skeleton are present and importable.

This is the bootstrap gate. It asserts the directory layout exists, the
`scripts` packages import cleanly (so later slices can hang contracts, router,
families, and the CLI off them), the offline fixtures tree exists, and SKILL.md
carries a `validator-gate` frontmatter name so the gate is discoverable. No
behavior is implemented yet; later slices fill these packages in test-first.
"""

from __future__ import annotations

import importlib
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def test_skill_layout_present() -> None:
    for rel in (
        "SKILL.md",
        "pytest.ini",
        "scripts/__init__.py",
        "scripts/families/__init__.py",
        "schemas",
        "tests/conftest.py",
        "tests/fixtures/evidence_packs",
    ):
        assert (SKILL_ROOT / rel).exists(), f"missing skeleton path: {rel}"


def test_scripts_packages_import() -> None:
    # The skill root is on sys.path via conftest; these must import as packages.
    assert importlib.import_module("scripts") is not None
    assert importlib.import_module("scripts.families") is not None


def test_skill_md_declares_validator_gate_name() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "SKILL.md must open with YAML frontmatter"
    head = text.split("---", 2)[1]
    assert "name: validator-gate" in head, "SKILL.md frontmatter must declare name: validator-gate"
