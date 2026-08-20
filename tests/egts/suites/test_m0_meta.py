"""EGTS-M0 meta-tests: no-effect proof, seeded-bad controls, coverage completeness.

This is the credibility core of the M0 proof (EGTS-M0-7): the Evaluation Core is
structurally effect-free, the primary artifacts reject the exact false-confidence
encodings the project forbids, and every EG-M0 obligation is covered. A green
EGTS-M0 here means *real EvalGlass cannot quietly overclaim at M0* (tests/CLAUDE.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from evalglass.core import ContractError
from evalglass.core.results import RunRecord
from evalglass.core.scores import Score
from evalglass.core.verdict import VerdictPayload
from tests.egts.coverage_registry import (
    CoverageRegistry,
    find_gaps,
    integrity_violations,
    load_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


# --- no-effect proof --------------------------------------------------------


def test_evaluation_core_is_effect_free() -> None:
    """The Evaluation Core imports no I/O / vendor / clock / randomness (CLAUDE.md §4)."""
    sys.path.insert(0, str(_REPO_ROOT / "tools"))
    from check_core_isolation import scan  # the isolation tool lives outside the package

    violations = scan([_REPO_ROOT / "src" / "evalglass" / "core"])
    assert violations == [], f"core is not effect-free: {violations}"


# --- seeded-bad negative controls: the primary artifacts must fail closed ----


def test_blocked_score_encoded_as_zero_is_rejected() -> None:
    """A blocked measurement encoded as 0.0 is the cardinal lie — it must not parse."""
    with pytest.raises(ContractError):
        Score.from_dict(
            {
                "metric": "faithfulness",
                "value": 0.0,  # blocked must carry no value
                "status": "blocked",
                "validity": "not_measured",
                "evaluator_version": "j@1",
            }
        )


def test_mutated_verdict_payload_is_rejected() -> None:
    """A payload claiming pass while a gate failed must not parse (reports trust it)."""
    with pytest.raises(ContractError):
        VerdictPayload.from_dict(
            {
                "verdict": "pass",
                "ci_should_fail": False,
                "passing_gates": [],
                "failing_gates": ["accuracy"],
                "blocked_gates": [],
                "informational_metrics": [],
                "reasons": {},
            }
        )


def test_runrecord_with_blocked_zero_score_is_rejected() -> None:
    """The same lie inside a full RunRecord artifact is rejected end to end."""
    bad = {
        "run_id": "r",
        "scorecard": {
            "verdict": {
                "verdict": "blocked",
                "ci_should_fail": True,
                "blocked_gates": ["m"],
                "passing_gates": [],
                "failing_gates": [],
                "informational_metrics": [],
                "reasons": {},
            },
            "metrics": [],
            "authority": {},
        },
        "scores": [
            {
                "metric": "m",
                "value": 0.0,
                "status": "blocked",
                "validity": "not_measured",
                "evaluator_version": "m@1",
            }
        ],
        "provenance": {"dimensions": {}},
    }
    with pytest.raises(ContractError):
        RunRecord.from_dict(bad)


# --- coverage completeness --------------------------------------------------


def _eg_m0_registry() -> CoverageRegistry:
    return load_registry(_REPO_ROOT / "tests" / "egts" / "coverage" / "eg_m0.yaml")


def test_eg_m0_coverage_is_complete() -> None:
    """Every EG-M0 obligation is covered by a real scenario — no gaps, no overclaim."""
    registry = _eg_m0_registry()
    assert integrity_violations(registry) == []
    gaps = find_gaps(registry)
    assert gaps == [], f"uncovered EG-M0 obligations: {[g.product_ticket for g in gaps]}"


def test_coverage_ids_reference_real_egts_scenarios() -> None:
    """A covered row may only cite scenario ids that egts test-core actually runs."""
    from tests.egts.suites import M0_SCENARIO_IDS

    for row in _eg_m0_registry().rows:
        unknown = [sid for sid in row.scenario_ids if sid not in M0_SCENARIO_IDS]
        assert not unknown, f"{row.product_ticket} cites non-EGTS scenario(s): {unknown}"
