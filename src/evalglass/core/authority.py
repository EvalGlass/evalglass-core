"""Authority resolution (EG-M0-5a).

Authority is typed data, not report prose (``CLAUDE.md §11``). :func:`resolve_authority`
turns the typed authority inputs (dataset status, metric status, threshold
approval, judge calibration, data policy, baseline comparability) into a
:class:`ResolvedAuthority`:

* ``INFORMATIONAL`` — the metric is not authorized to gate yet (proposed data,
  proposed threshold, non-gating metric status, uncalibrated judge). No active
  gate; the run stays informational.
* ``GATING`` + ``blocked`` — the metric is configured to gate but its evidence
  cannot support an honest claim (forbidden/missing/unknown policy, drifted judge,
  retired dataset, or a required baseline that is not comparable).
* ``GATING`` + ``can_gate`` — fully authorized; the Verdict Engine may pass/fail it.

Effect-free, stdlib-only. The Verdict Engine (verdict.py) consumes this; no other
component may compute authority.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import ContractError, _coerce_enum, _opt_str_list, _require
from evalglass.core.contracts import DataPolicy
from evalglass.core.grant import GrantStatus, GrantVerification
from evalglass.core.provenance import BaselineState


class DatasetStatus(enum.StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    RETIRED = "retired"


class MetricStatus(enum.StrEnum):
    DRAFT = "draft"
    INFORMATIONAL = "informational"
    CALIBRATING = "calibrating"
    GATING = "gating"
    RETIRED = "retired"


class ThresholdApproval(enum.StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"


class JudgeCalibration(enum.StrEnum):
    UNCALIBRATED = "uncalibrated"
    CALIBRATING = "calibrating"
    CALIBRATED = "calibrated"
    DRIFTED = "drifted"
    RETIRED = "retired"


class JudgeCapability(enum.StrEnum):
    """What a judge *is*, independent of any calibration record it carries (M7 T3, G3).

    Capability precedes authority: a synthetic test double can never gate, no matter
    what dataset/threshold/calibration surrounds it, because approval cannot turn a
    non-measurement into a measurement (the "fake judge can gate" hole alpha left in
    ``runner._apply_calibration``). This is checked *before* calibration in stage 1.
    """

    MEASUREMENT = "measurement"  # a real judge instrument; may earn authority once calibrated
    SYNTHETIC_TEST_DOUBLE = (
        "synthetic_test_double"  # the fake judge; structurally non-authoritative
    )

    @property
    def authority_eligible(self) -> bool:
        return self is JudgeCapability.MEASUREMENT


class AuthorityLevel(enum.StrEnum):
    NONE = "none"
    INFORMATIONAL = "informational"
    GATING = "gating"


_POLICY_OK = frozenset({DataPolicy.PERMITTED, DataPolicy.REDACTED})


@dataclass(frozen=True)
class AuthorityInputs:
    """The typed inputs to authority resolution for a single metric."""

    metric_status: MetricStatus
    dataset_status: DatasetStatus
    threshold_approval: ThresholdApproval
    data_policy: DataPolicy
    judge_calibration: JudgeCalibration | None = None
    # Additive (M7 T3, G3): the judge's capability, set by the harness from the judge
    # kind. Default None = no judge / capability not asserted (backward-compatible).
    judge_capability: JudgeCapability | None = None
    # Additive (M7 T3, G3 / N2): the digest-match outcome of a referenced AuthorityGrant.
    # Default None = no grant machinery engaged (backward-compatible). MATCHED is a no-op;
    # MISSING/MISMATCHED -> informational; EXPIRED -> blocked.
    grant_verification: GrantVerification | None = None
    requires_baseline: bool = False
    baseline_state: BaselineState | None = None


@dataclass(frozen=True)
class ResolvedAuthority:
    """Whether a metric may gate, and why."""

    can_gate: bool
    level: AuthorityLevel
    blocked: bool
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Only three states are valid; reject contradictory combinations (fail closed)
        # so downstream verdict code can never read inconsistent gating/blocking flags.
        if self.can_gate and self.blocked:
            raise ContractError("ResolvedAuthority: can_gate and blocked cannot both be true")
        if (self.can_gate or self.blocked) and self.level is not AuthorityLevel.GATING:
            raise ContractError("ResolvedAuthority: can_gate/blocked require level=gating")
        if self.level is AuthorityLevel.GATING and not (self.can_gate or self.blocked):
            raise ContractError("ResolvedAuthority: level=gating must either gate or block")

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_gate": self.can_gate,
            "level": self.level.value,
            "blocked": self.blocked,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ContractError(f"ResolvedAuthority: expected a mapping, got {type(data).__name__}")
        can_gate = _require(data, "can_gate", "ResolvedAuthority")
        blocked = _require(data, "blocked", "ResolvedAuthority")
        if not isinstance(can_gate, bool) or not isinstance(blocked, bool):
            raise ContractError("ResolvedAuthority: 'can_gate' and 'blocked' must be booleans")
        return cls(
            can_gate=can_gate,
            level=_coerce_enum(
                AuthorityLevel,
                _require(data, "level", "ResolvedAuthority"),
                "level",
                "ResolvedAuthority",
            ),
            blocked=blocked,
            reasons=_opt_str_list(data, "reasons", "ResolvedAuthority"),
        )


def resolve_authority(inputs: AuthorityInputs) -> ResolvedAuthority:
    """Resolve typed authority inputs into can-gate / informational / blocked."""
    # 1) Not authorized to gate yet -> informational (no active gate).
    not_authorized: list[str] = []
    # Capability precedes everything: a non-authoritative judge (the fake) can never
    # gate, even with a validated dataset, approved threshold, and a calibration record
    # (M7 T3, G3 / redesign N3). Checked before calibration so approval can't rescue it.
    if inputs.judge_capability is not None and not inputs.judge_capability.authority_eligible:
        not_authorized.append("judge_fake_non_authoritative")
    # A referenced grant that doesn't match the current rig never earned authority for it.
    if inputs.grant_verification is not None and inputs.grant_verification.status in (
        GrantStatus.MISSING,
        GrantStatus.MISMATCHED,
    ):
        not_authorized.append(f"grant_{inputs.grant_verification.status.value}")
    if inputs.metric_status is not MetricStatus.GATING:
        not_authorized.append(f"metric_status={inputs.metric_status.value}")
    if inputs.threshold_approval is not ThresholdApproval.APPROVED:
        not_authorized.append("threshold_proposed")
    if inputs.dataset_status is DatasetStatus.PROPOSED:
        not_authorized.append("dataset_proposed")
    if inputs.judge_calibration in (JudgeCalibration.UNCALIBRATED, JudgeCalibration.CALIBRATING):
        not_authorized.append(f"judge_{inputs.judge_calibration.value}")
    if not_authorized:
        return ResolvedAuthority(
            can_gate=False,
            level=AuthorityLevel.INFORMATIONAL,
            blocked=False,
            reasons=not_authorized,
        )

    # 2) Configured to gate, but evidence cannot support an honest claim -> blocked.
    blocks: list[str] = []
    if inputs.data_policy not in _POLICY_OK:
        blocks.append(f"policy_{inputs.data_policy.value}")
    if inputs.judge_calibration in (JudgeCalibration.DRIFTED, JudgeCalibration.RETIRED):
        blocks.append(f"judge_{inputs.judge_calibration.value}")
    if inputs.dataset_status is DatasetStatus.RETIRED:
        blocks.append("dataset_retired")
    # An expired grant had authority and lost it -> block, not silently informational.
    if (
        inputs.grant_verification is not None
        and inputs.grant_verification.status is GrantStatus.EXPIRED
    ):
        blocks.append("grant_expired")
    if inputs.requires_baseline and inputs.baseline_state is not BaselineState.COMPARABLE:
        state = inputs.baseline_state.value if inputs.baseline_state else "missing"
        blocks.append(f"baseline_{state}")
    if blocks:
        return ResolvedAuthority(
            can_gate=False, level=AuthorityLevel.GATING, blocked=True, reasons=blocks
        )

    # 3) Fully authorized.
    return ResolvedAuthority(can_gate=True, level=AuthorityLevel.GATING, blocked=False, reasons=[])
