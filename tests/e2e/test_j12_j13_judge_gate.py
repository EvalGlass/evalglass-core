"""J12 calibrate-a-judge + J13 promote-a-gate verdict matrix (EG-AT6-6; plan §F 8.6/8.7).

A numeric judge score and a configured gate are not authority. Proven end-to-end (an uncalibrated
judge scores but cannot gate; a host-promoted gate passes) and across the authority matrix (the
calibration ladder, and dropping any one precondition keeps the gate closed with a typed reason).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost

pytestmark = pytest.mark.fixture_e2e


def _full_gate(**overrides: object) -> AuthorityInputs:
    """The full host-promoted gating chain for a judge metric, with single-field overrides."""
    base: dict[str, object] = {
        "metric_status": MetricStatus.GATING,
        "dataset_status": DatasetStatus.VALIDATED,
        "threshold_approval": ThresholdApproval.APPROVED,
        "data_policy": DataPolicy.PERMITTED,
        "judge_calibration": JudgeCalibration.CALIBRATED,
    }
    base.update(overrides)
    return AuthorityInputs(**base)  # type: ignore[arg-type]


# --- J12 / J13 end-to-end ---------------------------------------------------
def test_j12_uncalibrated_judge_scores_but_cannot_gate(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    host = make_host(AuthorityState.UNCALIBRATED_JUDGE)
    result = vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    scorecard = result.scorecard
    assert scorecard is not None
    assert scorecard["verdict"]["verdict"] == "informational"
    judge = next(iter(scorecard["authority"].values()))
    assert judge["can_gate"] is False
    assert "judge_uncalibrated" in judge["reasons"]
    # ...yet the judge produced a real value (number is not permission).
    assert any(m["status_counts"].get("scored") for m in scorecard["metrics"])


def test_j13_host_promoted_gate_passes(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    host = make_host(AuthorityState.HOST_PROMOTED_GATE)
    result = vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    scorecard = result.scorecard
    assert scorecard is not None
    assert scorecard["verdict"]["verdict"] == "pass"
    assert scorecard["verdict"]["ci_should_fail"] is False
    assert any(a["can_gate"] for a in scorecard["authority"].values())


# --- J12 calibration ladder (authority matrix) ------------------------------
def test_j12_calibrated_judge_can_gate() -> None:
    assert resolve_authority(_full_gate()).can_gate is True


def test_j12_uncalibrated_judge_cannot_gate() -> None:
    resolved = resolve_authority(_full_gate(judge_calibration=JudgeCalibration.UNCALIBRATED))
    assert resolved.can_gate is False
    assert "judge_uncalibrated" in resolved.reasons


def test_j12_drifted_judge_reverts_to_blocked() -> None:
    resolved = resolve_authority(_full_gate(judge_calibration=JudgeCalibration.DRIFTED))
    assert resolved.can_gate is False
    assert resolved.blocked is True
    assert "judge_drifted" in resolved.reasons


# --- J13 drop-one-precondition matrix ---------------------------------------
@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"metric_status": MetricStatus.INFORMATIONAL}, "metric_status=informational"),
        ({"dataset_status": DatasetStatus.PROPOSED}, "dataset_proposed"),
        ({"threshold_approval": ThresholdApproval.PROPOSED}, "threshold_proposed"),
        ({"judge_calibration": JudgeCalibration.UNCALIBRATED}, "judge_uncalibrated"),
    ],
)
def test_j13_dropping_one_precondition_keeps_gate_closed(
    override: dict[str, object], reason: str
) -> None:
    resolved = resolve_authority(_full_gate(**override))
    assert resolved.can_gate is False, f"gate stayed open after dropping a precondition: {override}"
    assert reason in resolved.reasons, f"missing the specific typed reason {reason!r}"
