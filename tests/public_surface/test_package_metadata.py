"""Public-surface snapshot tests (placeholder for M0).

Real snapshots (CLI ``--help`` text, scorecard JSON schema, contract types)
land alongside the M0 / M1 milestones. This file pins the *shape* of the test
family so the CI job has a target from day one.

See CLAUDE.md §9 ("Public surface tests") and §11 (anti-patterns).
"""

from __future__ import annotations

import pytest

import evalglass


@pytest.mark.public_surface
def test_package_exposes_version() -> None:
    """``evalglass.__version__`` is part of the public contract."""
    assert isinstance(evalglass.__version__, str)
    assert evalglass.__version__ != ""


@pytest.mark.public_surface
def test_subpackages_importable() -> None:
    """The three architectural seams must be importable as named in CLAUDE.md §4."""
    import evalglass.adapters
    import evalglass.core
    import evalglass.harness  # noqa: F401
