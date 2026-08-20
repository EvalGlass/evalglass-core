"""Paired baseline comparison over shared items (M7 T5, G6).

Alpha's baseline was a comparability *boolean*: the fingerprint either matched or it
didn't, and no delta was ever computed — "regression" could not be quantified. This
module adds the missing half: when a current run and its baseline share ``example_id``s,
it pairs the per-item scores, computes the item-level differences, and puts a Student-t
interval on the paired difference. An improvement/regression label is licensed only when
that interval clears zero; otherwise the change is ``within_noise`` — the redesign's rule
that a dropped number is not a regression until the evidence says so.

Pairing uses more information than comparing two independent means (each item is its own
control), so the interval is tighter and assumes less. Effect-free, stdlib-only.
See ``docs/TETA_REDESIGN.md`` §6.2.
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
    _opt_str_list,
    _require,
)
from evalglass.core.estimate import Interval, IntervalMethod
from evalglass.core.provenance import BaselineState
from evalglass.core.registry import Direction
from evalglass.core.scores import Score
from evalglass.core.statistics import DEFAULT_LEVEL, mean_interval


class DeltaOutcome(enum.StrEnum):
    IMPROVEMENT = "improvement"
    REGRESSION = "regression"
    WITHIN_NOISE = "within_noise"
    UNRESOLVED = "unresolved"  # too few paired items to resolve


class ComparisonPurpose(enum.StrEnum):
    """Why this baseline was chosen for comparison (extensible; ``previous_verified`` is future)."""

    PROMOTED_BASELINE = "promoted_baseline"


@dataclass(frozen=True)
class MetricDelta:
    """The paired change for one metric: mean item difference + its interval + verdict.

    ``delta`` is the raw mean per-item difference (current - baseline). ``direction_adjusted_delta``
    normalizes its sign so a positive value always means *improvement* (it equals ``delta`` for a
    higher-is-better metric and ``-delta`` for a lower-is-better one) — the value a renderer shows
    as a signed improvement/regression, while the raw delta is retained.
    """

    metric: str
    n_paired: int
    delta: float | None
    direction_adjusted_delta: float | None
    interval: Interval | None
    outcome: DeltaOutcome

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "n_paired": self.n_paired,
            "delta": self.delta,
            "outcome": self.outcome.value,
        }
        if self.direction_adjusted_delta is not None:
            out["direction_adjusted_delta"] = self.direction_adjusted_delta
        if self.interval is not None:
            out["interval"] = self.interval.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "MetricDelta")
        n_paired = _require(m, "n_paired", "MetricDelta")
        if isinstance(n_paired, bool) or not isinstance(n_paired, int) or n_paired < 0:
            raise ContractError("MetricDelta: 'n_paired' must be a non-negative integer")
        return cls(
            metric=str(_require(m, "metric", "MetricDelta")),
            n_paired=n_paired,
            delta=_opt_number(m, "delta", "MetricDelta"),
            direction_adjusted_delta=_opt_number(m, "direction_adjusted_delta", "MetricDelta"),
            interval=(
                Interval.from_dict(_as_mapping(m["interval"], "MetricDelta.interval"))
                if m.get("interval") is not None
                else None
            ),
            outcome=_coerce_enum(
                DeltaOutcome, _require(m, "outcome", "MetricDelta"), "outcome", "MetricDelta"
            ),
        )


@dataclass(frozen=True)
class PairedComparison:
    """The item-paired comparison of a run against its baseline."""

    baseline_run_id: str | None
    deltas: dict[str, MetricDelta] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"deltas": {k: v.to_dict() for k, v in self.deltas.items()}}
        if self.baseline_run_id is not None:
            out["baseline_run_id"] = self.baseline_run_id
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "PairedComparison")
        deltas_raw = _as_mapping(
            _require(m, "deltas", "PairedComparison"), "PairedComparison.deltas"
        )
        baseline_run_id = m.get("baseline_run_id")
        if baseline_run_id is not None and not isinstance(baseline_run_id, str):
            raise ContractError("PairedComparison: 'baseline_run_id' must be a string or null")
        return cls(
            baseline_run_id=baseline_run_id,
            deltas={str(k): MetricDelta.from_dict(v) for k, v in deltas_raw.items()},
        )


def _by_example(scores: Sequence[Score], metric: str) -> dict[str, float]:
    """Aggregatable (scored+valid) values for ``metric``, keyed by example_id."""
    out: dict[str, float] = {}
    for s in scores:
        if s.metric == metric and s.is_aggregatable and s.value is not None and s.example_id:
            out[s.example_id] = s.value
    return out


def _classify(mean_diff: float, interval: Interval | None, direction: Direction) -> DeltaOutcome:
    if interval is None:
        return DeltaOutcome.UNRESOLVED
    if interval.lower <= 0.0 <= interval.upper:
        return DeltaOutcome.WITHIN_NOISE
    better_when_positive = direction is Direction.HIGHER_IS_BETTER
    improved = (mean_diff > 0.0) == better_when_positive
    return DeltaOutcome.IMPROVEMENT if improved else DeltaOutcome.REGRESSION


def metric_delta(
    metric: str,
    current: Sequence[Score],
    baseline: Sequence[Score],
    direction: Direction,
    *,
    level: float = DEFAULT_LEVEL,
) -> MetricDelta:
    """Paired delta for one metric over the example_ids both runs scored aggregatably."""
    cur = _by_example(current, metric)
    base = _by_example(baseline, metric)
    shared = sorted(set(cur) & set(base))
    diffs = [cur[eid] - base[eid] for eid in shared]
    n = len(diffs)
    if n == 0:
        return MetricDelta(metric, 0, None, None, None, DeltaOutcome.UNRESOLVED)
    mean_diff = sum(diffs) / n
    band = mean_interval(diffs, level) if n >= 2 else None
    interval = Interval(IntervalMethod.STUDENT_T, level, band[0], band[1]) if band else None
    adjusted = mean_diff if direction is Direction.HIGHER_IS_BETTER else -mean_diff
    return MetricDelta(
        metric, n, mean_diff, adjusted, interval, _classify(mean_diff, interval, direction)
    )


def paired_comparison(
    current: Sequence[Score],
    baseline: Sequence[Score],
    directions: Mapping[str, Direction],
    *,
    baseline_run_id: str | None = None,
    level: float = DEFAULT_LEVEL,
) -> PairedComparison:
    """Compare a run against its baseline, item-paired per metric.

    ``directions`` maps each metric to its declared direction (the caller supplies it
    from the current run's specs); a metric absent from it is a setup error, never a
    silently mis-signed regression.
    """
    metrics = sorted({s.metric for s in current} | {s.metric for s in baseline})
    deltas: dict[str, MetricDelta] = {}
    for metric in metrics:
        if metric not in directions:
            raise ContractError(f"paired_comparison: no direction supplied for metric {metric!r}")
        deltas[metric] = metric_delta(metric, current, baseline, directions[metric], level=level)
    return PairedComparison(baseline_run_id=baseline_run_id, deltas=deltas)


def _opt_number(m: Mapping[str, Any], key: str, ctx: str) -> float | None:
    value = m.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{ctx}: {key!r} must be a number or null")
    return float(value)


@dataclass(frozen=True)
class ComparisonResult:
    """The run's typed, comparability-qualified comparison against a baseline (Epic D / D4).

    The single primary carrier of "did quality change": a numeric per-metric delta exists **only**
    when ``state`` is ``comparable``; every other state records *why* no delta can be claimed (a
    ``not_comparable`` run lists the changed fingerprint dimensions). This is evidence, not verdict:
    it carries no ``ci_should_fail`` and never sets an exit code — a regression that should fail CI
    flows through the single Verdict Engine on a comparable baseline, never through this object.
    """

    purpose: ComparisonPurpose
    state: BaselineState
    baseline_run_id: str | None = None
    changed_dimensions: list[str] = field(default_factory=list)
    comparison: PairedComparison | None = None
    skipped_metrics: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # A numeric delta is licensed only by a comparable state; any other state must carry no
        # paired comparison, and a comparable state must carry one (fail closed on a contradiction).
        if self.state is BaselineState.COMPARABLE and self.comparison is None:
            raise ContractError(
                "ComparisonResult: a comparable state must carry a paired comparison"
            )
        if self.state is not BaselineState.COMPARABLE and self.comparison is not None:
            raise ContractError(
                "ComparisonResult: only a comparable state may carry a paired comparison"
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"purpose": self.purpose.value, "state": self.state.value}
        if self.baseline_run_id is not None:
            out["baseline_run_id"] = self.baseline_run_id
        if self.changed_dimensions:
            out["changed_dimensions"] = list(self.changed_dimensions)
        if self.comparison is not None:
            out["comparison"] = self.comparison.to_dict()
        if self.skipped_metrics:
            out["skipped_metrics"] = list(self.skipped_metrics)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "ComparisonResult")
        comparison_raw = m.get("comparison")
        return cls(
            purpose=_coerce_enum(
                ComparisonPurpose,
                _require(m, "purpose", "ComparisonResult"),
                "purpose",
                "ComparisonResult",
            ),
            state=_coerce_enum(
                BaselineState, _require(m, "state", "ComparisonResult"), "state", "ComparisonResult"
            ),
            baseline_run_id=(
                str(m["baseline_run_id"]) if m.get("baseline_run_id") is not None else None
            ),
            changed_dimensions=_opt_str_list(m, "changed_dimensions", "ComparisonResult"),
            comparison=(
                PairedComparison.from_dict(
                    _as_mapping(comparison_raw, "ComparisonResult.comparison")
                )
                if comparison_raw is not None
                else None
            ),
            skipped_metrics=_opt_str_list(m, "skipped_metrics", "ComparisonResult"),
        )


def build_comparison(
    *,
    current_scores: Sequence[Score],
    baseline_scores: Sequence[Score] | None,
    baseline_run_id: str | None,
    state: BaselineState,
    directions: Mapping[str, Direction],
    changed_dimensions: Sequence[str] = (),
    purpose: ComparisonPurpose = ComparisonPurpose.PROMOTED_BASELINE,
    level: float = DEFAULT_LEVEL,
) -> ComparisonResult:
    """Build the run's typed comparison from the verified baseline and the comparability state.

    A paired per-metric delta is computed **only** when ``state`` is ``comparable``; a
    ``not_comparable`` state records the changed fingerprint dimensions and no delta; missing /
    not-requested states carry neither. A metric with no declared direction is *skipped* (listed),
    never a silently mis-signed regression. Pairs by shared stable ``example_id`` (never list
    position). This is the single builder both a normal ``run`` and the drift watcher use, so their
    comparison semantics cannot diverge.
    """
    if state is not BaselineState.COMPARABLE or baseline_scores is None:
        changed = list(changed_dimensions) if state is BaselineState.NOT_COMPARABLE else []
        return ComparisonResult(
            purpose=purpose,
            state=state,
            baseline_run_id=baseline_run_id,
            changed_dimensions=changed,
        )
    metrics = {s.metric for s in current_scores} | {s.metric for s in baseline_scores}
    usable = {name: directions[name] for name in metrics if name in directions}
    skipped = sorted(metrics - set(usable))
    cur = [s for s in current_scores if s.metric in usable]
    base = [s for s in baseline_scores if s.metric in usable]
    paired = paired_comparison(cur, base, usable, baseline_run_id=baseline_run_id, level=level)
    return ComparisonResult(
        purpose=purpose,
        state=state,
        baseline_run_id=baseline_run_id,
        comparison=paired,
        skipped_metrics=skipped,
    )
