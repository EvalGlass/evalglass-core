"""DecisionPolicy: what it takes for an estimate to clear a gate (M7 T2, G2).

The redesign's third separation is *estimate is not decision*. Alpha's verdict
compared the bare **point estimate** to the threshold and blocked only on an
all-or-nothing "any example excluded" rule — so a one-item, interval-less
estimate could pass. A :class:`DecisionPolicy` makes the decision rule explicit
and host-owned:

* which **statistic** is compared — the point, or (safer, and the default) the
  confidence bound on the threatened side (lower bound for higher-is-better,
  upper bound for lower-is-better);
* the **minimum effective n** below which the gate blocks rather than guesses;
* the **maximum missing fraction** of evidence the decision tolerates;
* the interval **level** and any **required study** prerequisite.

The policy is content-addressed (:meth:`digest`) so an :class:`AuthorityGrant`
(T3) can bind an approval to the exact policy it approved — change any field and
the approval no longer matches.

Effect-free, stdlib-only. :func:`apply_policy` is the pure decision the Verdict
Engine consumes; this module never *is* the verdict. See ``docs/TETA_REDESIGN.md`` §4.5.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import ContractError, _as_mapping, _coerce_enum, _opt_str, _require
from evalglass.core.estimate import Estimate
from evalglass.core.registry import Direction


class DecisionStatistic(enum.StrEnum):
    POINT = "point"
    LOWER_CONFIDENCE_BOUND = "lower_confidence_bound"
    UPPER_CONFIDENCE_BOUND = "upper_confidence_bound"


@dataclass(frozen=True)
class DecisionPolicy:
    """A host-owned, content-addressed rule for turning an estimate into pass/fail/block."""

    threshold: float
    direction: Direction
    decision_statistic: DecisionStatistic | None = None  # None -> conservative bound for direction
    min_n_effective: int = 2
    max_missing_fraction: float = 0.0
    interval_level: float = 0.95
    required_study: str | None = None
    policy_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, int | float):
            raise ContractError("DecisionPolicy.threshold must be a number")
        if not math.isfinite(self.threshold):
            raise ContractError("DecisionPolicy.threshold must be finite")
        if isinstance(self.min_n_effective, bool) or not isinstance(self.min_n_effective, int):
            raise ContractError("DecisionPolicy.min_n_effective must be an int")
        if self.min_n_effective < 1:
            raise ContractError("DecisionPolicy.min_n_effective must be >= 1")
        if not (0.0 <= self.max_missing_fraction <= 1.0):
            raise ContractError("DecisionPolicy.max_missing_fraction must be in [0, 1]")
        if not (0.0 < self.interval_level < 1.0):
            raise ContractError("DecisionPolicy.interval_level must be in (0, 1)")

    def effective_statistic(self) -> DecisionStatistic:
        """Resolve the safe-by-direction default: LCB for higher-is-better, UCB otherwise."""
        if self.decision_statistic is not None:
            return self.decision_statistic
        if self.direction is Direction.HIGHER_IS_BETTER:
            return DecisionStatistic.LOWER_CONFIDENCE_BOUND
        return DecisionStatistic.UPPER_CONFIDENCE_BOUND

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "threshold": self.threshold,
            "direction": self.direction.value,
            "min_n_effective": self.min_n_effective,
            "max_missing_fraction": self.max_missing_fraction,
            "interval_level": self.interval_level,
        }
        if self.decision_statistic is not None:
            out["decision_statistic"] = self.decision_statistic.value
        if self.required_study is not None:
            out["required_study"] = self.required_study
        if self.policy_id is not None:
            out["policy_id"] = self.policy_id
        return out

    def digest(self) -> str:
        """Content address over every decision-bearing field (T3 grant binding).

        The resolved (direction-aware) statistic is hashed, so two policies that
        decide identically hash identically even if one left the statistic implicit.
        """
        payload = {
            "threshold": self.threshold,
            "direction": self.direction.value,
            "decision_statistic": self.effective_statistic().value,
            "min_n_effective": self.min_n_effective,
            "max_missing_fraction": self.max_missing_fraction,
            "interval_level": self.interval_level,
            "required_study": self.required_study,
            "policy_id": self.policy_id,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "DecisionPolicy")
        threshold = _require(m, "threshold", "DecisionPolicy")
        if isinstance(threshold, bool) or not isinstance(threshold, int | float):
            raise ContractError("DecisionPolicy: 'threshold' must be a number")
        stat_raw = m.get("decision_statistic")
        return cls(
            threshold=float(threshold),
            direction=_coerce_enum(
                Direction, _require(m, "direction", "DecisionPolicy"), "direction", "DecisionPolicy"
            ),
            decision_statistic=(
                _coerce_enum(DecisionStatistic, stat_raw, "decision_statistic", "DecisionPolicy")
                if stat_raw is not None
                else None
            ),
            min_n_effective=_int_field(m, "min_n_effective", 2),
            max_missing_fraction=_float_field(m, "max_missing_fraction", 0.0),
            interval_level=_float_field(m, "interval_level", 0.95),
            required_study=_opt_str(m, "required_study", "DecisionPolicy"),
            policy_id=_opt_str(m, "policy_id", "DecisionPolicy"),
        )


def _int_field(m: Mapping[str, Any], key: str, default: int) -> int:
    v = m.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ContractError(f"DecisionPolicy: '{key}' must be an int")
    return v


def _float_field(m: Mapping[str, Any], key: str, default: float) -> float:
    v = m.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ContractError(f"DecisionPolicy: '{key}' must be a number")
    return float(v)


@dataclass(frozen=True)
class DecisionOutcome:
    """The result of applying a policy to an estimate: pass, fail, or blocked (why)."""

    passed: bool | None  # None == blocked; the gate could not honestly decide
    statistic: DecisionStatistic
    statistic_value: float | None
    block_reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.passed is None


def apply_policy(
    policy: DecisionPolicy, estimate: Estimate, *, missing_fraction: float = 0.0
) -> DecisionOutcome:
    """Decide a gate from an estimate under a policy — pure; the Verdict Engine calls this.

    Blocks (``passed is None``) rather than guessing when evidence is inadequate:
    no measured value, too few effective samples, too much missing evidence, or a
    required confidence bound that the estimate does not carry.
    """
    stat = policy.effective_statistic()
    if estimate.point is None:
        return DecisionOutcome(None, stat, None, "no_measured_value")
    if estimate.n_effective < policy.min_n_effective:
        return DecisionOutcome(None, stat, None, "insufficient_samples")
    if missing_fraction > policy.max_missing_fraction:
        return DecisionOutcome(None, stat, None, "excessive_missing_evidence")

    if stat is DecisionStatistic.POINT:
        value = estimate.point
    else:
        if estimate.interval is None:
            return DecisionOutcome(None, stat, None, "decision_statistic_unavailable")
        value = (
            estimate.interval.lower
            if stat is DecisionStatistic.LOWER_CONFIDENCE_BOUND
            else estimate.interval.upper
        )

    if policy.direction is Direction.HIGHER_IS_BETTER:
        passed = value >= policy.threshold
    else:
        passed = value <= policy.threshold
    return DecisionOutcome(passed, stat, value, None)
