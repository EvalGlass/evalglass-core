"""EGP-A1-1..4: the authoring tier scaffolds host-owned assets without manufacturing authority.

The v1.1 authoring verbs (`add-metric`, `add-judge`, `calibrate`) and their backing skills help a
host author metrics, evaluators, judges, and calibration — but every generated asset stays
``proposed``/uncalibrated/empty-authority (ADR 0025), and gate activation remains a host YAML edit
guided by `promoting-a-gate` with **no** gate-activation verb. These assertions pin those
delivery invariants on the skill prose (the agent does the work; the host validates).
"""

from __future__ import annotations

import re

from tests.plugin.conftest import REPO_ROOT, skill_files

_AUTHORING_SKILLS = {
    "authoring-a-metric",
    "writing-a-host-evaluator",
    "calibrating-a-judge",
    "promoting-a-gate",
}
_UMBRELLA = REPO_ROOT / "skills" / "evalglass" / "SKILL.md"

# A gate-activation verb is forbidden (§9.9 / ADR 0022): gating is a host YAML edit.
_GATE_VERB = re.compile(r"/evalglass\s+(?:promote-gate|gate|approve|certify)\b", re.IGNORECASE)


def _skill(name: str) -> str:
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_authoring_skills_present() -> None:
    names = {p.parent.name for p in skill_files()}
    assert names >= _AUTHORING_SKILLS, f"missing authoring skills: {_AUTHORING_SKILLS - names}"


def test_add_metric_scaffolds_proposed_only() -> None:
    text = _norm(_skill("authoring-a-metric"))
    assert "proposed" in text
    # a new metric cannot gate by default and never writes an approved threshold
    assert "cannot gate" in text or "informational" in text
    assert "approved" in text  # discusses the (host-owned) approval it must NOT do


def test_host_evaluator_skill_preserves_score_semantics() -> None:
    text = _norm(_skill("writing-a-host-evaluator"))
    assert "scorebatch" in text or "score" in text
    # non-scored states are diagnostics, never 0.0
    assert "0.0" in text
    # host evaluator code stays host-owned and never imports the plugin/runtime
    assert "_evalglass" in text or "host-owned" in text
    assert "import" in text


def test_calibrate_keeps_judges_uncalibrated_until_host_records_it() -> None:
    text = _norm(_skill("calibrating-a-judge"))
    assert "uncalibrated" in text
    assert "cannot gate" in text or "until" in text
    # calibrate records host-owned evidence; it never self-approves a gate
    assert "never" in text


def test_promoting_a_gate_is_guidance_only_no_verb() -> None:
    raw = _skill("promoting-a-gate")
    assert _GATE_VERB.search(raw) is None, "promoting-a-gate must not introduce a gate verb"
    text = _norm(raw)
    # it explains the host-owned activation (editing YAML + the validation checklist)
    assert "yaml" in text or "evalglass.yaml" in text
    assert "validat" in text


def test_no_promote_gate_verb_in_any_skill() -> None:
    for skill in skill_files():
        assert "promote-gate" not in skill.read_text(encoding="utf-8").lower(), (
            f"{skill}: 'promote-gate' verb was removed and must not return"
        )


def test_umbrella_routes_authoring_verbs() -> None:
    text = _norm(_UMBRELLA.read_text(encoding="utf-8"))
    for verb in ("add-metric", "add-judge", "calibrate"):
        assert verb in text, f"umbrella must route the v1.1 authoring verb {verb!r}"
    # gate activation is guidance, not a verb
    assert _GATE_VERB.search(_UMBRELLA.read_text(encoding="utf-8")) is None
