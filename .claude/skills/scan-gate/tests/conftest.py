"""Shared pytest wiring for the scan-gate skill suite.

Puts the skill root on sys.path so tests can `import scripts...` once the CLI
and detectors land in later slices, and exposes a `fixtures_dir` fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent

if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


@pytest.fixture
def fixtures_dir() -> Path:
    return SKILL_ROOT / "tests" / "fixtures"
