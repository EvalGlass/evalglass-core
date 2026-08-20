"""R-tranche (live-connector) release readiness — the go/no-go end state (EG-R5-1/2/3/6).

The hermetic gate (``test_release_readiness_hermetic.py``) is kept frozen as the foundation/hermetic
record. THIS gate is the executable go/no-go for the live-connector tranche (EG-R0…R5): full
``egts coverage --require-complete`` is green at seven covered / one reasoned-deferred row, the one
deferred row (EG-M5C-7) is the ADR-backed never-build, the three provider connectors stay opt-in
(never promoted into the required runtime), and the real validator-gate passes the honest m5c pack
(now carrying connector evidence) while failing the connector overclaim shapes.

A green here is the single go signal for the live-connector tranche.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from evalglass.harness.lanes import Maturity, built_in_lanes
from tests.egts.coverage_registry import CoverageStatus, load_registry

_ROOT = Path(__file__).resolve().parents[1]
_COVERAGE = _ROOT / "tests" / "egts" / "coverage" / "eg_m5c.yaml"
_VALIDATOR = _ROOT / ".claude" / "skills" / "validator-gate" / "scripts" / "validator.py"
_PACK = _ROOT / "tests" / "egts" / "evidence" / "m5c_acceptance.pack.json"
_ADRS = _ROOT / "adrs"

_R_TRANCHE_COVERED = {f"EG-M5C-{n}" for n in (1, 2, 3, 4, 5, 6, 8)}
_NEVER_BUILD = "EG-M5C-7"
_CONNECTOR_LANES = ("langfuse-trace", "phoenix-trace", "langsmith-trace")


def test_full_coverage_end_state_is_seven_covered_one_reasoned_deferral() -> None:
    """EG-M5C-1/2/3/4/5/6/8 covered with scenario ids; only EG-M5C-7 deferred, with a reason."""
    registry = load_registry(_COVERAGE)
    covered = {r.product_ticket for r in registry.rows if r.status is CoverageStatus.COVERED}
    deferred = {r.product_ticket for r in registry.rows if r.status is CoverageStatus.NOT_STARTED}
    assert covered == _R_TRANCHE_COVERED
    assert deferred == {_NEVER_BUILD}
    for row in registry.rows:
        if row.status is CoverageStatus.COVERED:
            assert row.scenario_ids, f"{row.product_ticket}: a covered row needs scenario ids"
        else:
            assert row.not_exercised_reason
            assert row.not_exercised_reason.strip()
            assert not row.scenario_ids


def test_require_complete_gate_exits_zero() -> None:
    """The full ``egts coverage --require-complete`` gate exits 0 — a reasoned deferral is not a
    gap, but an UNreasoned not_started or a covered-without-scenario row would fail it."""
    completed = subprocess.run(  # noqa: S603 - trusted interpreter + fixed in-repo module
        [
            sys.executable,
            "-m",
            "tests.egts.cli",
            "coverage",
            "--require-complete",
            "--registry",
            str(_COVERAGE),
        ],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        check=False,
    )
    assert completed.returncode == 0, (
        f"require-complete failed: {completed.stdout}{completed.stderr}"
    )


def test_never_build_row_is_adr_backed() -> None:
    """EG-M5C-7 stays a never-build, and its reason cites a real, indexed ADR (EG-R5-6) — a deferral
    is honest only when it points at a recorded decision, not a vague 'later'."""
    row = next(r for r in load_registry(_COVERAGE).rows if r.product_ticket == _NEVER_BUILD)
    assert row.status is CoverageStatus.NOT_STARTED
    reason = row.not_exercised_reason or ""
    assert "ADR 0037" in reason, "the never-build reason must cite its ADR"
    adr = _ADRS / "0037-per-source-function-view-not-built.md"
    assert adr.is_file(), "ADR 0037 (per-source-function never-build) must exist"
    assert adr.name in (_ADRS / "README.md").read_text(encoding="utf-8"), "ADR 0037 must be indexed"


def test_connectors_stay_opt_in_never_required() -> None:
    """The three provider connectors are covered yet remain opt-in: each lane is conservatively
    mature (never ``now``) and pins its own optional SDK extra, so coverage never makes a provider
    SDK a required runtime dependency."""
    registry = built_in_lanes()
    for name in _CONNECTOR_LANES:
        lane = registry.get(name)
        assert lane.maturity is not Maturity.NOW, f"{name} must never be a 'now' default"
        assert lane.optional_dependencies, f"{name} must pin its own opt-in SDK extra"


def test_validator_gate_passes_the_honest_connector_inclusive_pack() -> None:
    """The real validator-gate PASSES the committed m5c pack now that it carries connector
    lane-result evidence (the overclaim variants fail in test_m5c_validator_gate_acceptance)."""
    completed = subprocess.run(  # noqa: S603 - trusted interpreter + fixed in-repo script path
        [sys.executable, str(_VALIDATOR), "run", "--evidence-pack", str(_PACK)],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        check=False,
    )
    assert completed.returncode == 0, f"validator-gate failed the honest pack: {completed.stdout}"
