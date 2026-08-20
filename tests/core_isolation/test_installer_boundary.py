"""Import-boundary guard: the runtime never depends on the integration-time skill.

The vendored runtime (`core` / `harness` / `adapters`) must run after the skill and
the coding agent are gone (P13 boundary; ADR 0010). Structurally that means no
module under those packages may import `evalglass.installer`. This guard backs the
EGTS-M3-4 clean-subprocess proof with a fast, deterministic AST check.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"
_RUNTIME_PKGS = ("core", "harness", "adapters")


def _imports_skill(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                a.name == "evalglass.installer" or a.name.startswith("evalglass.installer.")
                for a in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "evalglass.installer" or mod.startswith("evalglass.installer."):
                return True
    return False


def test_runtime_packages_do_not_import_skill() -> None:
    offenders: list[str] = []
    for pkg in _RUNTIME_PKGS:
        for py in (_SRC / pkg).rglob("*.py"):
            if _imports_skill(py):
                offenders.append(str(py.relative_to(_SRC)))
    assert not offenders, (
        f"runtime packages import evalglass.installer (breaks runtime independence): {offenders}"
    )
