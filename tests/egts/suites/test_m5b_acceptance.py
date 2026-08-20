"""EGTS-M5-7 (complete) — M5 acceptance gate B (Evidence Governance, Integration Proof).

The final M5 gate: the complete optional-lane set is declared and **every lane is removable**
(no required path imports a lane), the M5b coverage registry is fully covered, and the richer-unit
+ governance surfaces are present. This is the "M5 done" proof — removing every optional lane
leaves the M1-M4 required suite green (the EG-M5 exit criterion).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from evalglass.core import EvalUnit, UnitKind
from evalglass.core.builtins import BUILTINS, trajectory_shape
from evalglass.harness import runner as _runner
from evalglass.harness.governance import import_synthetic_dataset
from evalglass.harness.lanes import built_in_lanes
from evalglass.harness.units import select_units
from tests.egts.checkers import check_lane_imports_isolated, check_lane_metadata
from tests.egts.coverage_registry import find_gaps, integrity_violations, load_registry

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"
_COVERAGE = Path(__file__).resolve().parents[1] / "coverage"

#: The built-in lane roster: the M5 optional-lane set (M5a integration lanes + M5b
#: async-observation) plus the v2 hermetic SCORE_SINK sinks ``hosted-dashboard`` and
#: ``optimizer-handoff`` (EG-H2), plus the ``langfuse-trace`` live connector (EG-R1; its
#: SDK is an opt-in extra, imported lazily — EG-M5C-6 coverage flips only at EG-R4).
_EXPECTED_LANES = {
    "live-judge",
    "trace-backend",
    "score-sink-export",
    "async-observation",
    "hosted-dashboard",
    "optimizer-handoff",
    "langfuse-trace",
    "phoenix-trace",
    "langsmith-trace",
}


def test_m5_complete_lane_set_is_declared() -> None:
    assert set(built_in_lanes().names()) == _EXPECTED_LANES


def test_m5_every_lane_is_declared_and_removable() -> None:
    """Each optional lane declares its contract and no required module imports it (deletable)."""
    for lane in built_in_lanes().lanes():
        check_lane_metadata(lane)
        check_lane_imports_isolated(_SRC, lane.module)


def test_m5b_coverage_registry_is_fully_covered() -> None:
    registry = load_registry(_COVERAGE / "eg_m5b.yaml")
    assert find_gaps(registry) == []
    assert integrity_violations(registry) == []


def test_m5a_coverage_registry_is_fully_covered() -> None:
    registry = load_registry(_COVERAGE / "eg_m5a.yaml")
    assert find_gaps(registry) == []
    assert integrity_violations(registry) == []


def test_m5_richer_unit_surface_present() -> None:
    # Richer units: the kinds, the members field, and the aggregate built-in all exist.
    assert {UnitKind.STEP, UnitKind.TRAJECTORY, UnitKind.SESSION} <= set(UnitKind)
    assert EvalUnit(unit_id="u", kind=UnitKind.TRAJECTORY, trace_id="t", members=["a"]).members == [
        "a"
    ]
    assert trajectory_shape.VERSION in BUILTINS


def test_m5_selector_has_production_caller() -> None:
    """EG-P1 updated the M5b intent: ``select_units`` is no longer import-only — the runner
    now calls it from ``run_config``'s ``_load_trace_units`` to build config-reachable
    trajectory/session units (ADR 0045). The behavior itself is proved in
    ``test_p1_trajectory_units_proof``; here we pin that a production caller exists.
    """
    assert select_units.__name__ == "select_units"
    assert "select_units(" in inspect.getsource(_runner._load_trace_units)


def test_m5_governance_surface_present() -> None:
    # Generated-evidence governance: synthetic data is non-authoritative by construction.
    assert import_synthetic_dataset("g", 1).status.value == "proposed"
