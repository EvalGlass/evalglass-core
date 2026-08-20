"""Shared pytest wiring for the validator-gate skill suite.

Puts the skill root on sys.path so tests can `import scripts...` as the
contracts, evidence reader, router, families, composer, and CLI land in later
slices. Exposes a `fixtures_dir` fixture pointing at the offline evidence-pack
fixtures. The suite is self-contained and runs offline.
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
