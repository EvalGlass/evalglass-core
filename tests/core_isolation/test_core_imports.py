"""Structural test: the Evaluation Core has no I/O / vendor / clock imports.

This test wraps ``tools.check_core_isolation`` so the same gate is enforced by:
    * pre-commit hooks (running the CLI directly),
    * the pytest fast suite (this test),
    * the ``core-isolation`` CI job (running the CLI directly).

See CLAUDE.md §4 and §9.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from check_core_isolation import scan  # noqa: E402 — import after sys.path tweak

CORE_PATH = REPO_ROOT / "src" / "evalglass" / "core"


@pytest.mark.core_isolation
def test_core_has_no_forbidden_imports() -> None:
    """The Evaluation Core must not import any forbidden module."""
    violations = scan([CORE_PATH])
    if violations:
        formatted = "\n".join(f"  {v.render(REPO_ROOT)}" for v in violations)
        pytest.fail(
            "Evaluation Core contains forbidden imports / calls. "
            "See CLAUDE.md §4. Move effects into the Runtime Harness or an adapter.\n" + formatted
        )
