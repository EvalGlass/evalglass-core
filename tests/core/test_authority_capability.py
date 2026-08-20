"""Capability-typed authority: a fake judge can never gate (M7 T3, G3).

This closes the alpha hole where FakeJudgeModel gated exactly like a live judge
given a hand-written calibration file (runner._apply_calibration). Capability is
checked in stage 1, before calibration, so no surrounding approval can rescue it.

See src/evalglass/core/authority.py and docs/TETA_REDESIGN.md §2 (G3), N3.
"""

from __future__ import annotations

from evalglass.core.authority import (
    AuthorityInputs,
    AuthorityLevel,
    DatasetStatus,
    JudgeCalibration,
    JudgeCapability,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy


def _fully_gating(**overrides: object) -> AuthorityInputs:
    """Everything a gate needs — validated data, approved threshold, calibrated judge."""
    base: dict[str, object] = {
        "metric_status": MetricStatus.GATING,
        "dataset_status": DatasetStatus.VALIDATED,
        "threshold_approval": ThresholdApproval.APPROVED,
        "data_policy": DataPolicy.PERMITTED,
        "judge_calibration": JudgeCalibration.CALIBRATED,
    }
    base.update(overrides)
    return AuthorityInputs(**base)  # type: ignore[arg-type]


def test_capability_eligibility() -> None:
    assert JudgeCapability.MEASUREMENT.authority_eligible
    assert not JudgeCapability.SYNTHETIC_TEST_DOUBLE.authority_eligible


def test_fake_judge_cannot_gate_even_when_everything_else_is_authorized() -> None:
    resolved = resolve_authority(
        _fully_gating(judge_capability=JudgeCapability.SYNTHETIC_TEST_DOUBLE)
    )
    assert resolved.level is AuthorityLevel.INFORMATIONAL
    assert resolved.can_gate is False
    assert resolved.blocked is False
    assert "judge_fake_non_authoritative" in resolved.reasons


def test_measurement_capability_still_gates() -> None:
    resolved = resolve_authority(_fully_gating(judge_capability=JudgeCapability.MEASUREMENT))
    assert resolved.can_gate is True
    assert resolved.level is AuthorityLevel.GATING


def test_absent_capability_preserves_prior_behavior() -> None:
    # Backward compatibility: no capability asserted -> unchanged resolution.
    resolved = resolve_authority(_fully_gating())
    assert resolved.can_gate is True


def test_fake_capability_beats_a_calibrated_record() -> None:
    # Even an (illegitimately) calibrated fake judge is informational, not gating:
    # the capability check runs before the calibration check.
    resolved = resolve_authority(
        _fully_gating(
            judge_capability=JudgeCapability.SYNTHETIC_TEST_DOUBLE,
            judge_calibration=JudgeCalibration.CALIBRATED,
        )
    )
    assert resolved.can_gate is False
    assert "judge_fake_non_authoritative" in resolved.reasons
