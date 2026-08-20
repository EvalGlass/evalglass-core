"""EGP-P0-7: the single SessionStart bootstrap is display-only, exit-0, and state-free.

The hook is the one always-on surface. Binding rules (ADR 0022; plan §4.4 Hooks): it exits 0
unconditionally, points only to the umbrella skill, and echoes no scorecard/runrecord/verdict/
authority/gate/quality state or any capability claim.
"""

from __future__ import annotations

import json
import subprocess

from tests.plugin.conftest import REPO_ROOT

_HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
_BOOTSTRAP = REPO_ROOT / "hooks" / "session-start.sh"

#: Tokens that would mean the bootstrap is reading/echoing run state or claiming quality.
_FORBIDDEN_OUTPUT = (
    "verdict",
    "scorecard",
    "runrecord",
    "authority",
    "gate",
    "calibrat",
    "threshold",
    "pass",
    "fail",
    "blocked",
    "quality",
    "score",
    "correct",
    "safe",
)


def test_hooks_json_shape() -> None:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    session = data["hooks"]["SessionStart"]
    assert isinstance(session, list), "SessionStart must be a list"
    assert session, "expected at least one SessionStart entry"
    entry = session[0]
    assert entry["matcher"] == "startup|clear|compact"
    inner = entry["hooks"]
    assert len(inner) == 1, "exactly one bootstrap hook (the only v1 hook)"
    hook = inner[0]
    assert hook["type"] == "command"
    assert hook["async"] is False
    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]
    assert "hooks/session-start.sh" in hook["command"]


def test_no_other_hook_events() -> None:
    """v1 ships only SessionStart — no PostToolUse (cut from v1, plan §4.4)."""
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    assert set(data["hooks"]) == {"SessionStart"}


def test_bootstrap_executable() -> None:
    import os

    assert os.access(_BOOTSTRAP, os.X_OK), "session-start.sh must be executable"


def test_bootstrap_exits_zero_and_points_to_umbrella() -> None:
    result = subprocess.run(  # noqa: S603 — fixed absolute path, no shell, test-only
        [str(_BOOTSTRAP)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, (
        f"bootstrap must exit 0; got {result.returncode}, stderr={result.stderr!r}"
    )
    out = result.stdout.strip()
    assert out, "bootstrap must emit a skill-discovery pointer"
    assert "/evalglass" in out, "bootstrap must point to the umbrella skill"


def test_bootstrap_emits_no_state_or_quality_tokens() -> None:
    result = subprocess.run(  # noqa: S603 — fixed absolute path, no shell, test-only
        [str(_BOOTSTRAP)], capture_output=True, text=True, timeout=10, check=False
    )
    low = result.stdout.lower()
    leaked = [tok for tok in _FORBIDDEN_OUTPUT if tok in low]
    assert not leaked, f"bootstrap echoed forbidden state/quality token(s): {leaked}"
