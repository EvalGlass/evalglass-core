"""The Estimate: a metric's population claim with honest uncertainty (M7 T1, G1).

Alpha stopped at :class:`AggregatedMetric` — a point value plus coverage counts.
The redesign's second separation is *score is not estimate*: a point is not the
quantity a decision compares to a threshold. :class:`Estimate` adds the interval
(and the assumptions that produced it) on top of the point, without changing the
point itself (``estimate`` reuses :func:`aggregate`, so ``Estimate.point`` and
``AggregatedMetric.value`` can never disagree).

The interval method is chosen from the metric's declared meaning, not guessed:

* a **binary** metric aggregated as a rate/mean is a **proportion** → Wilson;
* a **continuous** metric aggregated as a mean → **Student-t**;
* ``min``/``max``/``median`` (order statistics) get a point and an explicit "no
  interval defined for this aggregation" diagnostic — an honest absence, not a
  fabricated band.

Effect-free, stdlib-only. See ``docs/TETA_REDESIGN.md`` §5.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _as_mapping,
    _coerce_enum,
    _require,
    _require_str,
)
from evalglass.core.aggregation import aggregate
from evalglass.core.contracts import Diagnostic, Severity
from evalglass.core.registry import Aggregation, MetricSpec, ScoreType
from evalglass.core.scores import Score, aggregatable
from evalglass.core.statistics import (
    DEFAULT_LEVEL,
    mean_interval,
    rule_of_three_upper,
    wilson_interval,
)

_SMALL_N = 5  # below this a mean interval is flagged low-reliability (descriptive only)


class IntervalMethod(enum.StrEnum):
    WILSON = "wilson"
    STUDENT_T = "student_t"
    NONE = "none"


@dataclass(frozen=True)
class Interval:
    """A named, two-sided confidence interval. The method records the assumptions."""

    method: IntervalMethod
    level: float
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.method is IntervalMethod.NONE:
            raise ContractError("Interval.method must name a real method (not 'none')")
        if not (0.0 < self.level < 1.0):
            raise ContractError(f"Interval.level must be in (0, 1), got {self.level!r}")
        if self.lower > self.upper:
            raise ContractError(f"Interval lower ({self.lower}) must be <= upper ({self.upper})")

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "level": self.level,
            "lower": self.lower,
            "upper": self.upper,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Interval")
        method = _coerce_enum(
            IntervalMethod, _require(m, "method", "Interval"), "method", "Interval"
        )
        level = _require(m, "level", "Interval")
        lower = _require(m, "lower", "Interval")
        upper = _require(m, "upper", "Interval")
        for name, val in (("level", level), ("lower", lower), ("upper", upper)):
            if isinstance(val, bool) or not isinstance(val, int | float):
                raise ContractError(f"Interval: '{name}' must be a number, got {val!r}")
        return cls(method=method, level=float(level), lower=float(lower), upper=float(upper))


@dataclass(frozen=True)
class Estimate:
    """A metric's point estimate plus its interval, effective n, and diagnostics."""

    metric: str
    point: float | None
    n_effective: int
    interval: Interval | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.n_effective, bool) or not isinstance(self.n_effective, int):
            raise ContractError("Estimate.n_effective must be an int")
        if self.n_effective < 0:
            raise ContractError("Estimate.n_effective must be non-negative")
        if self.point is None and self.interval is not None:
            raise ContractError("Estimate: an interval requires a point estimate")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "point": self.point,
            "n_effective": self.n_effective,
        }
        if self.interval is not None:
            out["interval"] = self.interval.to_dict()
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Estimate")
        point = _require(m, "point", "Estimate")
        if point is not None and (isinstance(point, bool) or not isinstance(point, int | float)):
            raise ContractError("Estimate: 'point' must be a number or null")
        n_eff = _require(m, "n_effective", "Estimate")
        if isinstance(n_eff, bool) or not isinstance(n_eff, int) or n_eff < 0:
            raise ContractError("Estimate: 'n_effective' must be a non-negative integer")
        interval_raw = m.get("interval")
        diagnostics = [
            Diagnostic.from_dict(_as_mapping(d, "Estimate.diagnostics"))
            for d in (m.get("diagnostics") or [])
        ]
        return cls(
            metric=_require_str(m, "metric", "Estimate"),
            point=None if point is None else float(point),
            n_effective=n_eff,
            interval=(
                Interval.from_dict(_as_mapping(interval_raw, "Estimate.interval"))
                if interval_raw is not None
                else None
            ),
            diagnostics=diagnostics,
        )


def _eligible_values(metric: str, scores: Sequence[Score]) -> list[float]:
    own = [s for s in scores if s.metric == metric]
    return [s.value for s in aggregatable(own) if s.value is not None]


def estimate(spec: MetricSpec, scores: Sequence[Score], level: float = DEFAULT_LEVEL) -> Estimate:
    """Compute a metric's :class:`Estimate` from its scores, honest about uncertainty.

    ``point`` is taken from :func:`aggregate` (one source of truth); the interval is
    selected from the metric's declared score type and aggregation.
    """
    point = aggregate(spec.name, scores, spec.aggregation).value
    values = _eligible_values(spec.name, scores)
    n = len(values)
    interval, diagnostics = _interval_for(spec, values, point, n, level)
    return Estimate(
        metric=spec.name, point=point, n_effective=n, interval=interval, diagnostics=diagnostics
    )


def _interval_for(
    spec: MetricSpec, values: list[float], point: float | None, n: int, level: float
) -> tuple[Interval | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if point is None or n == 0 or spec.aggregation is Aggregation.NONE:
        return None, diagnostics

    is_proportion = spec.score_type is ScoreType.BINARY and spec.aggregation in (
        Aggregation.RATE,
        Aggregation.MEAN,
    )
    if is_proportion:
        successes = sum(1 for v in values if v >= 0.5)
        lo, hi = wilson_interval(successes, n, level)
        if successes in (0, n):
            unobserved = "failure" if successes == n else "success"
            diagnostics.append(
                Diagnostic(
                    code="rule_of_three",
                    severity=Severity.INFO,
                    message=(
                        f"all {n} eligible observations were the same outcome; the "
                        f"empirical band is zero-width, so the 95% upper bound on the "
                        f"unobserved {unobserved} rate is reported instead."
                    ),
                    details={f"{unobserved}_rate_95pct_upper_bound": rule_of_three_upper(n)},
                )
            )
        return Interval(IntervalMethod.WILSON, level, lo, hi), diagnostics

    if spec.aggregation is Aggregation.MEAN:  # continuous mean
        band = mean_interval(values, level)
        if band is None:
            diagnostics.append(_small_n_diag(n))
            return None, diagnostics
        if n < _SMALL_N:
            diagnostics.append(_small_n_diag(n))
        # Clamp the (domain-agnostic) Student-t interval to the metric's declared range: a
        # bounded [low, high] metric can never have a true mean outside its range, so an interval
        # bound beyond it is a modeling artefact, not honest uncertainty.
        lo, hi = band
        if spec.score_range is not None:
            low, high = spec.score_range
            lo, hi = max(low, lo), min(high, hi)
        return Interval(IntervalMethod.STUDENT_T, level, lo, hi), diagnostics

    # min / max / median: an order statistic has no simple confidence interval here.
    diagnostics.append(
        Diagnostic(
            code="no_interval_for_aggregation",
            severity=Severity.INFO,
            message=(
                f"aggregation '{spec.aggregation.value}' reports an order statistic; "
                "no confidence interval is defined for it, so the point stands alone."
            ),
        )
    )
    return None, diagnostics


def _small_n_diag(n: int) -> Diagnostic:
    return Diagnostic(
        code="low_reliability_small_n",
        severity=Severity.WARNING,
        message=(
            f"only {n} eligible observation(s); any interval is descriptive sampling "
            f"uncertainty, not a reliability estimate (n < {_SMALL_N})."
        ),
        details={"n_effective": n, "small_n_threshold": _SMALL_N},
    )
