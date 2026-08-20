"""EXTENSION_GOVERNANCE prose stays consistent with the live coverage registry (audit P1-B).

The audit found the shipped governance doc still said `EG-M5C-6` "stays not_started" while the
shipped coverage registry marks it covered — a tracked-doc-vs-registry contradiction. This guard
pins the consistency so the prose cannot drift from the registry again: if a future change flips
the EG-M5C-6 coverage row, the doc must move with it (and vice versa). Test-only.
"""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

_ROOT = Path(__file__).resolve().parents[2]
_GOVERNANCE = _ROOT / "docs" / "EXTENSION_GOVERNANCE.md"
_COVERAGE = _ROOT / "tests" / "egts" / "coverage" / "eg_m5c.yaml"


def _eg_m5c_6_status() -> str:
    rows = yaml.safe_load(_COVERAGE.read_text(encoding="utf-8"))["rows"]
    row = next(r for r in rows if r["product_ticket"] == "EG-M5C-6")
    return str(row["status"])


def test_governance_prose_matches_the_eg_m5c_6_coverage_row() -> None:
    """While EG-M5C-6 is covered, the governance doc must not claim it is still deferred/not_started
    (the contradiction the audit caught), and must state the covered/connectors-shipped reality."""
    text = _GOVERNANCE.read_text(encoding="utf-8")
    lowered = text.lower()
    if _eg_m5c_6_status() == "covered":
        # No stale deferral language for EG-M5C-6 (an underclaim vs the shipped registry).
        assert "eg-m5c-6` stays `not_started" not in lowered
        assert "eg-m5c-6 stays not_started" not in lowered
        # The doc affirmatively reflects the covered state.
        assert "eg-m5c-6` is now **`covered`**" in lowered or "eg-m5c-6` is `covered`" in lowered
