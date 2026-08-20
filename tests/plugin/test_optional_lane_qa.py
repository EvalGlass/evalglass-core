"""EGP-A1-8: the authoring tier and advanced lanes stay covered, consistent, and optional.

The final A1 gate extends the existing guardrails to every new surface (add-metric, add-judge,
calibrate, connect --live, connect --synth, source-correlation): the honesty-audit provably scans
them, the documented surface matches the on-disk skills (manifest-consistency), none ships an
authority verb, and an optional lane's absence never breaks the required local workflow (a fresh
install runs on non-reference built-ins alone — no judge/live/synth needed).
"""

from __future__ import annotations

import re
from pathlib import Path

import evalglass
from evalglass.installer.scaffold import scaffold
from evalglass.installer.vendor import vendor
from tests.plugin.conftest import REPO_ROOT, skill_files
from tests.plugin.test_honesty_audit import _audited_files

_A1_SKILLS = {
    "authoring-a-metric",
    "writing-a-host-evaluator",
    "calibrating-a-judge",
    "promoting-a-gate",
}
_SOURCE_CORR = REPO_ROOT / "plugin-docs" / "advanced-source-correlation.md"
_README = REPO_ROOT / "README.md"
_AUTHORITY_VERB = re.compile(
    r"/evalglass\s+(?:gate|approve|certify|verify|validate|score|pass|promote-gate)\b",
    re.IGNORECASE,
)


def test_honesty_audit_scope_covers_every_a1_surface() -> None:
    """The fail-closed prose gate must actually scan the new authoring + advanced prose."""
    scanned = set(_audited_files())
    for name in _A1_SKILLS:
        assert REPO_ROOT / "skills" / name / "SKILL.md" in scanned, f"{name} escapes honesty-audit"
    assert _SOURCE_CORR in scanned, "source-correlation note escapes the honesty-audit"


def test_v1_1_surface_is_documented_in_readme() -> None:
    """Manifest-consistency: the v1.1 verbs/lanes on disk are documented for the user."""
    text = " ".join(_README.read_text(encoding="utf-8").lower().split())
    for token in ("add-metric", "add-judge", "calibrate", "connect --live", "connect --synth"):
        assert token in text, f"README must document the v1.1 surface {token!r}"


def test_no_a1_skill_ships_an_authority_verb() -> None:
    for skill in skill_files():
        if skill.parent.name in _A1_SKILLS:
            hit = _AUTHORITY_VERB.search(skill.read_text(encoding="utf-8"))
            assert hit is None, f"{skill}: authority verb {hit.group(0) if hit else ''!r}"


def test_fresh_required_workflow_needs_no_optional_lane(tmp_path: Path) -> None:
    """A scaffolded host runs the required flow on built-ins alone — no judge/live/synth lane."""
    host = tmp_path / "host"
    host.mkdir()
    pkg = Path(evalglass.__file__).resolve().parent
    vendor(pkg, host, framework_version="1.0.0", source_ref="test")
    scaffold(host)
    config = (host / "evals" / "evalglass.yaml").read_text(encoding="utf-8").lower()
    for optional in ("judge_score", "--live", "connect --synth", "phoenix", "langfuse"):
        assert optional not in config, (
            f"fresh required config must not depend on the optional lane {optional!r}"
        )
