"""Honest aggregation over a metric's scores (EG-M0-4a).

Only ``scored`` + ``valid`` measurements enter the numeric math; every excluded
status is still counted so a summary cannot hide that inputs were blocked,
errored, or skipped (``CLAUDE.md §9``). An aggregate with no eligible inputs has
value ``None`` — never ``0.0``. Effect-free, stdlib-only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _coerce_enum,
    _opt_mapping,
    _require,
    _require_str,
)
from evalglass.core.registry import Aggregation
from evalglass.core.scores import Score, ScoreStatus, aggregatable


@dataclass(frozen=True)
class AggregatedMetric:
    """A metric's summary: aggregated value (or None), what was included, what was excluded."""

    metric: str
    aggregation: Aggregation
    value: float | None
    included_count: int
    status_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "aggregation": self.aggregation.value,
            "value": self.value,
            "included_count": self.included_count,
        }
        if self.status_counts:
            out["status_counts"] = dict(self.status_counts)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ContractError(f"AggregatedMetric: expected a mapping, got {type(data).__name__}")
        counts_raw = _opt_mapping(data, "status_counts", "AggregatedMetric")
        counts: dict[str, int] = {}
        for status_key, count in counts_raw.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ContractError(
                    f"AggregatedMetric: status_counts[{status_key!r}] "
                    "must be a non-negative integer"
                )
            counts[str(status_key)] = count
        included = _require(data, "included_count", "AggregatedMetric")
        if not isinstance(included, int) or isinstance(included, bool) or included < 0:
            raise ContractError("AggregatedMetric: 'included_count' must be a non-negative integer")
        value = _require(data, "value", "AggregatedMetric")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
            raise ContractError("AggregatedMetric: 'value' must be a number or null")
        return cls(
            metric=_require_str(data, "metric", "AggregatedMetric"),
            aggregation=_coerce_enum(
                Aggregation,
                _require(data, "aggregation", "AggregatedMetric"),
                "aggregation",
                "AggregatedMetric",
            ),
            value=value,
            included_count=included,
            status_counts=counts,
        )


def _reduce(kind: Aggregation, values: Sequence[float]) -> float | None:
    if not values:
        return None
    if kind is Aggregation.NONE:
        return None
    if kind is Aggregation.MEAN:
        return sum(values) / len(values)
    if kind is Aggregation.MIN:
        return min(values)
    if kind is Aggregation.MAX:
        return max(values)
    if kind is Aggregation.RATE:
        # success rate: the mean of normalized scores (for 0/1 binary, the pass
        # fraction). Deliberately NOT "fraction at the best observed value", which
        # would report 100% for an all-failure (all-0.0) binary metric.
        return sum(values) / len(values)
    # MEDIAN
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def aggregate(metric: str, scores: Sequence[Score], kind: Aggregation) -> AggregatedMetric:
    """Aggregate the scores *for* ``metric`` under ``kind``, counting excluded statuses.

    Only scores whose ``metric`` matches are considered; a mixed run-wide list
    cannot let another metric's scores leak into this summary.
    """
    own = [s for s in scores if s.metric == metric]
    status_counts: dict[str, int] = {}
    for score in own:
        key = score.status.value if isinstance(score.status, ScoreStatus) else str(score.status)
        status_counts[key] = status_counts.get(key, 0) + 1
    eligible = aggregatable(own)
    values = [s.value for s in eligible if s.value is not None]
    return AggregatedMetric(
        metric=metric,
        aggregation=kind,
        value=_reduce(kind, values),
        included_count=len(eligible),
        status_counts=status_counts,
    )
