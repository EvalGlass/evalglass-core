"""EGP-A1-5/6/7: advanced connectors and governance stay opt-in, honest, and non-authoritative.

`connect --live` is an isolated, opt-in, **deletable** optional lane (data-policy first, clean-skip
when prerequisites are absent, no provider SDK shipped). `connect --synth` returns the governance
truth (generated data is `proposed`, never validated gold; no generator is built). Per-source-
function viewing stays an advanced, unbuilt extension with explicit non-coverage language. These
assertions pin that delivery posture on the connect skill and the design note (ADR 0025).
"""

from __future__ import annotations

from pathlib import Path

from tests.plugin.conftest import REPO_ROOT

_CONNECT = REPO_ROOT / "skills" / "evaluate-an-agentic-app" / "SKILL.md"
_SOURCE_CORR = REPO_ROOT / "plugin-docs" / "advanced-source-correlation.md"
_UMBRELLA = REPO_ROOT / "skills" / "evalglass" / "SKILL.md"


def _norm(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_connect_live_is_opt_in_deletable_lane() -> None:
    text = _norm(_CONNECT)
    assert "connect --live" in text
    assert "opt-in" in text or "optional" in text
    assert "deletable" in text or "delete" in text  # removing the lane is safe
    assert "data policy" in text or "data-policy" in text  # enforced before any effect
    # absent prerequisites skip cleanly, and EvalGlass ships no provider SDK
    assert "skip" in text
    assert "no provider sdk" in text or "no sdk" in text


def test_connect_live_is_not_a_required_path() -> None:
    text = _norm(_CONNECT)
    # it is explicitly v1.1 / advanced, never part of the v1 required journey
    assert "v1.1" in text or "advanced" in text


def test_connect_synth_returns_governance_truth() -> None:
    text = _norm(_CONNECT)
    assert "connect --synth" in text
    assert "proposed" in text  # generated data is proposed, never gold
    assert "not built" in text or "no generator" in text  # the honest governance truth
    # never presented as validated gold
    assert "never" in text
    assert "gold" in text


def test_source_correlation_is_an_unbuilt_advanced_design_note() -> None:
    assert _SOURCE_CORR.is_file(), "advanced-source-correlation design note must exist (A1-7)"
    text = _norm(_SOURCE_CORR)
    assert "source" in text
    assert "function" in text
    # depends on F1 score identity AND trace↔call-site correlation that does not exist
    assert "example_id" in text or "subject identity" in text
    assert "does not exist" in text or "not built" in text or "not available" in text
    assert "advanced" in text


def test_advanced_connectors_grant_no_authority() -> None:
    """The advanced surfaces never make a run pass or grant authority."""
    import re

    gate_verb = re.compile(r"/evalglass\s+(?:gate|approve|certify|promote-gate)\b", re.IGNORECASE)
    for path in (_CONNECT, _SOURCE_CORR):
        assert gate_verb.search(path.read_text(encoding="utf-8")) is None
