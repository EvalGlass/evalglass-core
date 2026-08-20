"""Import-boundary guard: the required runtime never imports any optional extension lane.

Generalizes ``test_judge_live_boundary`` across every lane declared in
:func:`evalglass.harness.lanes.built_in_lanes`. A lane is opt-in and deletable (EG-M5-1; ADR 0017),
so no required module — ``core``, ``harness``, or any *other* adapter — may statically import a
lane's module. The framework resolves lanes lazily (``importlib.import_module``), so this AST scan
finding a static import of a lane module means a required path would break on deletion / pull in an
optional dependency. Fast, deterministic.
"""

from __future__ import annotations

import ast
from pathlib import Path

from evalglass.harness.lanes import built_in_lanes

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"
_REQUIRED_PKGS = ("core", "harness", "adapters")


def _module_file(dotted: str) -> Path:
    return (_SRC.parent / (dotted.replace(".", "/") + ".py")).resolve()


def _imports(path: Path, target: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == target for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "") == target:
            return True
    return False


def test_required_tier_does_not_statically_import_any_optional_lane() -> None:
    offenders: list[str] = []
    for lane in built_in_lanes().lanes():
        lane_file = _module_file(lane.module)
        for pkg in _REQUIRED_PKGS:
            for py in (_SRC / pkg).rglob("*.py"):
                if py.resolve() == lane_file:
                    continue
                if _imports(py, lane.module):
                    offenders.append(f"{py.relative_to(_SRC)} imports {lane.module}")
    assert not offenders, f"required modules statically import an optional lane: {offenders}"


def test_lane_framework_module_imports_no_concrete_lane() -> None:
    """harness/lanes.py must resolve lanes lazily — never statically import a lane module."""
    framework = _SRC / "harness" / "lanes.py"
    offenders = [
        lane.module for lane in built_in_lanes().lanes() if _imports(framework, lane.module)
    ]
    assert not offenders, f"the lane framework statically imports concrete lane(s): {offenders}"
