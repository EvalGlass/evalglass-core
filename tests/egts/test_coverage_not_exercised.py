"""EG-AT0-6 — coverage registry ``not_exercised_reason`` semantics.

Deferred v2 capabilities are represented honestly by reusing the existing
``not_started`` status plus a mandatory reason — no new ``CoverageStatus`` member.
A ``not_started`` row without a reason fails validation; with one it is an
honestly-accounted "NOT EXERCISED" obligation; a ``covered`` row still requires a
real scenario id.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from tests.egts.cli import main as egts_main
from tests.egts.coverage_registry import (
    CoverageError,
    CoverageStatus,
    parse_registry,
)


def _row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "product_ticket": "EG-AT0-6",
        "public_contract": "coverage not_exercised_reason",
        "status": "covered",
        "scenario_ids": ["at0.coverage.semantics"],
    }
    base.update(over)
    return base


def test_no_new_coverage_status_member() -> None:
    assert {s.value for s in CoverageStatus} == {
        "covered",
        "partial",
        "blocked",
        "optional",
        "not_started",
    }


def test_not_started_without_reason_fails_validation() -> None:
    with pytest.raises(CoverageError, match="not_exercised_reason"):
        parse_registry({"rows": [_row(status="not_started", scenario_ids=[])]})


def test_not_started_with_reason_is_accounted_not_a_gap() -> None:
    registry = parse_registry(
        {
            "rows": [
                _row(
                    status="not_started",
                    scenario_ids=[],
                    not_exercised_reason="dashboard sink not built; no required path loads it",
                )
            ]
        }
    )
    row = registry.rows[0]
    assert row.is_not_exercised is True
    assert row.is_satisfied is True  # honestly deferred, not an open gap


def test_blank_reason_is_treated_as_missing() -> None:
    with pytest.raises(CoverageError, match="not_exercised_reason"):
        parse_registry(
            {"rows": [_row(status="not_started", scenario_ids=[], not_exercised_reason="   ")]}
        )


def test_covered_row_still_requires_a_real_scenario_id() -> None:
    registry = parse_registry({"rows": [_row(status="covered", scenario_ids=[])]})
    assert registry.rows[0].is_integrity_violation is True


def test_cli_renders_not_exercised_with_reason(tmp_path: Path) -> None:
    registry_yaml = tmp_path / "eg_def.yaml"
    registry_yaml.write_text(
        "rows:\n"
        "  - product_ticket: EG-AT4-4\n"
        "    public_contract: hosted dashboard sink\n"
        "    status: not_started\n"
        "    not_exercised_reason: capability not built; no required path loads it\n",
        encoding="utf-8",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = egts_main(["coverage", "--registry", str(registry_yaml), "--require-complete"])
    out = buf.getvalue()
    assert code == 0  # an honestly-deferred row does not fail --require-complete
    assert "NOT EXERCISED — capability not built" in out
