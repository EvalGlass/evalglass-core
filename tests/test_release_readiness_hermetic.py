"""Foundation/hermetic tranche release readiness — the go/no-go end-state (EG-H5-6).

Makes the release readiness executable: the scoped coverage is exactly six covered hermetic rows
and two honestly-deferred rows, the runtime dependency budget is PyYAML-only, and the tranche's
guard suites are present. A green here is the single go signal for the foundation/hermetic tranche.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tests.egts.coverage_registry import CoverageStatus, load_registry

_ROOT = Path(__file__).resolve().parents[1]
_COVERAGE = _ROOT / "tests" / "egts" / "coverage" / "eg_m5c.yaml"
_PYPROJECT = _ROOT / "pyproject.toml"

#: The hermetic tranche's own rows — covered at EG-H5 and must STAY covered. The exact post-
#: R-tranche end state (which adds EG-M5C-6) is pinned by ``test_v2_coverage_registry``; this
#: hermetic gate is the frozen hermetic record and only asserts its own rows did not regress.
_HERMETIC_COVERED = {f"EG-M5C-{n}" for n in (1, 2, 3, 4, 5, 8)}


def test_hermetic_rows_stay_covered_and_per_source_function_stays_deferred() -> None:
    registry = load_registry(_COVERAGE)
    covered = {r.product_ticket for r in registry.rows if r.status is CoverageStatus.COVERED}
    deferred = {r.product_ticket for r in registry.rows if r.status is CoverageStatus.NOT_STARTED}
    assert covered >= _HERMETIC_COVERED, "a hermetic-tranche row regressed out of covered"
    assert "EG-M5C-7" in deferred, "per-source-function (EG-M5C-7) is the never-build"
    # Every covered row carries real scenarios; every deferred row carries a reason, no scenarios.
    for row in registry.rows:
        if row.status is CoverageStatus.COVERED:
            assert row.scenario_ids
        else:
            assert row.not_exercised_reason
            assert not row.scenario_ids


def test_runtime_dependency_budget_is_pyyaml_only() -> None:
    deps = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {re.split(r"[<>=!~;\[ ]", str(d), maxsplit=1)[0].strip().lower() for d in deps}
    assert names == {"pyyaml"}


def test_tranche_guard_suites_are_present() -> None:
    """The release relies on these guards staying in the required tier — fail if one is removed."""
    for rel in (
        "tests/test_dependency_budget.py",
        "tests/test_hermetic_tranche_lock.py",
        "tests/egts/suites/test_m5c_validator_gate_acceptance.py",
    ):
        assert (_ROOT / rel).is_file(), f"missing release guard suite: {rel}"
