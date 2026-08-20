"""The single Verdict Engine (EG-M0-5b).

This module owns the *only* path from measurement + authority to a run outcome
(``CLAUDE.md §4/§11``). No CLI, report, adapter, sink, or skill may reimplement
this logic. The engine consumes per-gate inputs (resolved authority + measured
value + approved threshold + direction) and emits a :class:`VerdictPayload`.

Precedence (most conservative first): a ``pass`` is never emitted while any active
gate fails or is blocked. When both blocked and failing gates exist the run is
``blocked`` — it cannot make an honest claim — but every gate list is preserved so
nothing is hidden. Effect-free, stdlib-only.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import ContractError, _coerce_enum, _opt_str_list, _require
from evalglass.core.authority import ResolvedAuthority
from evalglass.core.decision import DecisionPolicy, DecisionStatistic, apply_policy
from evalglass.core.estimate import Estimate
from evalglass.core.registry import Direction


class Verdict(enum.StrEnum):
    INFORMATIONAL = "informational"
    PASS = "pass"  # noqa: S105 — verdict enum value, not a credential
    FAIL = "fail"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class GateInput:
    """One metric's input to the Verdict Engine."""

    metric: str
    resolved: ResolvedAuthority
    value: float | None = None
    threshold: float | None = None
    direction: Direction = Direction.HIGHER_IS_BETTER
    #: How many of this metric's scores were excluded from aggregation (not
    #: scored+valid). A non-zero count means the measurement is incomplete, so an
    #: active gate cannot honestly pass/fail over the partial value — it blocks.
    excluded_count: int = 0
    #: Additive (M7 T2): when a DecisionPolicy is supplied the gate decides on the
    #: policy's statistic (default: the confidence bound on the threatened side) via
    #: apply_policy over the Estimate — so a one-item or wide-interval gate blocks/fails
    #: instead of passing on a point estimate. Absent -> the legacy point-vs-threshold
    #: path, so every existing gate is byte-identical.
    estimate: Estimate | None = None
    decision_policy: DecisionPolicy | None = None


@dataclass(frozen=True)
class VerdictPayload:
    """The Verdict Engine's output; reports and CI render from this, never recompute it."""

    verdict: Verdict
    ci_should_fail: bool
    passing_gates: list[str] = field(default_factory=list)
    failing_gates: list[str] = field(default_factory=list)
    blocked_gates: list[str] = field(default_factory=list)
    informational_metrics: list[str] = field(default_factory=list)
    reasons: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Reports and CI trust this payload instead of recomputing the verdict, so a
        # mutated/contradictory payload must fail closed rather than turn a recorded
        # failing/blocked gate into a pass (CLAUDE.md §11).
        if self.blocked_gates:
            expected = Verdict.BLOCKED
        elif self.failing_gates:
            expected = Verdict.FAIL
        elif self.passing_gates:
            expected = Verdict.PASS
        else:
            expected = Verdict.INFORMATIONAL
        if self.verdict is not expected:
            raise ContractError(
                f"VerdictPayload: verdict {self.verdict.value!r} is inconsistent with the gate "
                f"lists (precedence implies {expected.value!r})"
            )
        expected_ci = self.verdict in (Verdict.FAIL, Verdict.BLOCKED)
        if self.ci_should_fail != expected_ci:
            raise ContractError(
                f"VerdictPayload: ci_should_fail must be {expected_ci} for verdict "
                f"{self.verdict.value!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "ci_should_fail": self.ci_should_fail,
            "passing_gates": list(self.passing_gates),
            "failing_gates": list(self.failing_gates),
            "blocked_gates": list(self.blocked_gates),
            "informational_metrics": list(self.informational_metrics),
            "reasons": {k: list(v) for k, v in self.reasons.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ContractError(f"VerdictPayload: expected a mapping, got {type(data).__name__}")
        ci = _require(data, "ci_should_fail", "VerdictPayload")
        if not isinstance(ci, bool):
            raise ContractError("VerdictPayload: 'ci_should_fail' must be a boolean")
        reasons_raw = data.get("reasons", {})
        if not isinstance(reasons_raw, Mapping):
            raise ContractError("VerdictPayload: 'reasons' must be a mapping")
        reasons: dict[str, list[str]] = {}
        for key, value in reasons_raw.items():
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ContractError(f"VerdictPayload: reasons[{key!r}] must be a list of strings")
            reasons[str(key)] = list(value)
        return cls(
            verdict=_coerce_enum(
                Verdict, _require(data, "verdict", "VerdictPayload"), "verdict", "VerdictPayload"
            ),
            ci_should_fail=ci,
            passing_gates=_opt_str_list(data, "passing_gates", "VerdictPayload"),
            failing_gates=_opt_str_list(data, "failing_gates", "VerdictPayload"),
            blocked_gates=_opt_str_list(data, "blocked_gates", "VerdictPayload"),
            informational_metrics=_opt_str_list(data, "informational_metrics", "VerdictPayload"),
            reasons=reasons,
        )


def _passes(value: float, threshold: float, direction: Direction) -> bool:
    if direction is Direction.HIGHER_IS_BETTER:
        return value >= threshold
    return value <= threshold


def _policy_fail_reason(statistic: DecisionStatistic, direction: Direction) -> str:
    side = "below_threshold" if direction is Direction.HIGHER_IS_BETTER else "above_threshold"
    return f"{statistic.value}_{side}"


def _classify_active_gate(
    gate: GateInput,
    passing: list[str],
    failing: list[str],
    blocked: list[str],
    reasons: dict[str, list[str]],
) -> None:
    """Classify one authorized gate. Policy path (statistic + adequacy) or legacy point path."""
    if gate.decision_policy is not None and gate.estimate is not None:
        total = gate.excluded_count + gate.estimate.n_effective
        missing = gate.excluded_count / total if total else 0.0
        outcome = apply_policy(gate.decision_policy, gate.estimate, missing_fraction=missing)
        if outcome.blocked:
            blocked.append(gate.metric)
            reasons[gate.metric] = [outcome.block_reason or "gate_blocked"]
        elif outcome.passed:
            passing.append(gate.metric)
        else:
            failing.append(gate.metric)
            reasons[gate.metric] = [
                _policy_fail_reason(outcome.statistic, gate.decision_policy.direction)
            ]
        return

    # Legacy point-vs-threshold path (no policy configured) — unchanged.
    if gate.value is None:
        blocked.append(gate.metric)
        reasons[gate.metric] = ["no_measured_value"]
    elif gate.excluded_count > 0:
        blocked.append(gate.metric)
        reasons[gate.metric] = ["incomplete_measurement"]
    elif gate.threshold is None:
        blocked.append(gate.metric)
        reasons[gate.metric] = ["no_approved_threshold"]
    elif _passes(gate.value, gate.threshold, gate.direction):
        passing.append(gate.metric)
    else:
        failing.append(gate.metric)
        miss = (
            "below_threshold" if gate.direction is Direction.HIGHER_IS_BETTER else "above_threshold"
        )
        reasons[gate.metric] = [miss]


def decide_verdict(gates: Sequence[GateInput]) -> VerdictPayload:
    """Resolve per-gate inputs into the run's single verdict. The only verdict path."""
    passing: list[str] = []
    failing: list[str] = []
    blocked: list[str] = []
    informational: list[str] = []
    reasons: dict[str, list[str]] = {}

    for gate in gates:
        if gate.resolved.blocked:
            blocked.append(gate.metric)
            reasons[gate.metric] = list(gate.resolved.reasons) or ["gate_blocked"]
        elif gate.resolved.can_gate:
            _classify_active_gate(gate, passing, failing, blocked, reasons)
        else:
            informational.append(gate.metric)

    # Precedence: blocked > fail > pass > informational. Never pass with a
    # blocked or failing active gate present.
    if blocked:
        verdict, ci = Verdict.BLOCKED, True
    elif failing:
        verdict, ci = Verdict.FAIL, True
    elif passing:
        verdict, ci = Verdict.PASS, False
    else:
        verdict, ci = Verdict.INFORMATIONAL, False

    return VerdictPayload(
        verdict=verdict,
        ci_should_fail=ci,
        passing_gates=passing,
        failing_gates=failing,
        blocked_gates=blocked,
        informational_metrics=informational,
        reasons=reasons,
    )
