"""Import-boundary guard: the required runtime never imports the optional live judge lane.

The live judge lane (``adapters/judge_live.py``) is opt-in and deletable (EG-M4-5; ADR 0016).
No required module — ``core``, ``harness``, or any *other* adapter — may import it, so removing
it leaves the required suite green and the required tier stays hermetic (no provider lane in a
required import). Fast, deterministic AST check (mirrors the skill-boundary guard).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"
_LANE = "evalglass.adapters.judge_live"
_REQUIRED_PKGS = ("core", "harness", "adapters")


def _imports_lane(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == _LANE for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and (node.module or "") == _LANE:
            return True
    return False


def test_required_tier_does_not_import_the_live_lane() -> None:
    lane_file = _SRC / "adapters" / "judge_live.py"
    offenders: list[str] = []
    for pkg in _REQUIRED_PKGS:
        for py in (_SRC / pkg).rglob("*.py"):
            if py != lane_file and _imports_lane(py):
                offenders.append(str(py.relative_to(_SRC)))
    assert not offenders, f"required modules import the optional live judge lane: {offenders}"
