"""Authority resolution (EG-M0-5a).

Authority is typed data, not report prose (``CLAUDE.md §11``). A metric earns the
right to gate only when every input supports it: a validated dataset, a gating
metric status, an approved threshold, a calibrated judge (if any), permitted data
policy, and — for a regression gate — a comparable baseline. Anything not yet
authorized stays *informational* (no active gate); a metric configured to gate
whose evidence is missing/forbidden/non-comparable is *blocked* (it cannot make an
honest claim) — never silently gated.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.authority import (
    AuthorityInputs,
    AuthorityLevel,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ResolvedAuthority,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import ContractError, DataPolicy
from evalglass.core.provenance import BaselineState


def _gating(**over: object) -> AuthorityInputs:
    """Inputs for a metric fully authorized to gate."""
    base: dict[str, object] = {
        "metric_status": MetricStatus.GATING,
        "dataset_status": DatasetStatus.VALIDATED,
        "threshold_approval": ThresholdApproval.APPROVED,
        "data_policy": DataPolicy.PERMITTED,
    }
    base.update(over)
    return AuthorityInputs(**base)  # type: ignore[arg-type]


def test_fully_authorized_metric_can_gate() -> None:
    resolved = resolve_authority(_gating())
    assert resolved.can_gate is True
    assert resolved.level is AuthorityLevel.GATING
    assert resolved.blocked is False


@pytest.mark.parametrize(
    "over",
    [
        {"metric_status": MetricStatus.DRAFT},
        {"metric_status": MetricStatus.INFORMATIONAL},
        {"metric_status": MetricStatus.CALIBRATING},
        {"threshold_approval": ThresholdApproval.PROPOSED},
        {"dataset_status": DatasetStatus.PROPOSED},
        {"judge_calibration": JudgeCalibration.UNCALIBRATED},
        {"judge_calibration": JudgeCalibration.CALIBRATING},
    ],
)
def test_unauthorized_inputs_stay_informational(over: dict[str, object]) -> None:
    resolved = resolve_authority(_gating(**over))
    assert resolved.can_gate is False
    assert resolved.level is AuthorityLevel.INFORMATIONAL
    assert resolved.blocked is False
    assert resolved.reasons  # explains why it is only informational


@pytest.mark.parametrize(
    "over",
    [
        {"data_policy": DataPolicy.FORBIDDEN},
        {"data_policy": DataPolicy.MISSING},
        {"data_policy": DataPolicy.UNKNOWN},
        {"judge_calibration": JudgeCalibration.DRIFTED},
        {"dataset_status": DatasetStatus.RETIRED},
    ],
)
def test_configured_gate_with_bad_evidence_is_blocked(over: dict[str, object]) -> None:
    resolved = resolve_authority(_gating(**over))
    assert resolved.can_gate is False
    assert resolved.blocked is True
    assert resolved.reasons


def test_regression_gate_requires_comparable_baseline() -> None:
    comparable = resolve_authority(
        _gating(requires_baseline=True, baseline_state=BaselineState.COMPARABLE)
    )
    assert comparable.can_gate is True

    for state in (BaselineState.NOT_COMPARABLE, BaselineState.MISSING_BASELINE):
        blocked = resolve_authority(_gating(requires_baseline=True, baseline_state=state))
        assert blocked.can_gate is False
        assert blocked.blocked is True


def test_redacted_policy_can_still_gate() -> None:
    assert resolve_authority(_gating(data_policy=DataPolicy.REDACTED)).can_gate is True


def test_resolved_authority_round_trips() -> None:
    resolved = resolve_authority(_gating(metric_status=MetricStatus.DRAFT))
    assert ResolvedAuthority.from_dict(json.loads(json.dumps(resolved.to_dict()))) == resolved


def test_contradictory_authority_states_are_rejected() -> None:
    """Only resolve_authority's three states are valid; impossible combos fail closed."""
    with pytest.raises(ContractError):
        ResolvedAuthority.from_dict(
            {"can_gate": True, "blocked": True, "level": "gating", "reasons": []}
        )
    with pytest.raises(ContractError):
        ResolvedAuthority.from_dict(
            {"can_gate": True, "blocked": False, "level": "informational", "reasons": []}
        )
    with pytest.raises(ContractError):
        ResolvedAuthority(can_gate=False, level=AuthorityLevel.GATING, blocked=False)
