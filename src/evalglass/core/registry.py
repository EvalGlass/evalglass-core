"""MetricSpec and the metric registry (EG-M0-3a).

A ``MetricSpec`` declares a metric's meaning: lens, granularity, score type and
range, direction, evaluator reference, profile, required evidence, prerequisites,
aggregation, and the score names it emits. The :class:`MetricRegistry` validates
specs and rejects unknown metrics and undeclared emitted score names
(``CLAUDE.md §10``). Effect-free, stdlib-only — the evaluator protocol and
deterministic built-ins that produce scores against these specs follow in 5b.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _coerce_enum,
    _opt_mapping,
    _opt_str_list,
    _require,
    _require_str,
)
from evalglass.core.contracts import UnitKind


class Lens(enum.StrEnum):
    REFERENCE = "reference"
    NON_REFERENCE = "non_reference"


class ScoreType(enum.StrEnum):
    BINARY = "binary"
    CONTINUOUS = "continuous"
    CATEGORICAL = "categorical"


class Direction(enum.StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class Aggregation(enum.StrEnum):
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    RATE = "rate"
    NONE = "none"


@dataclass(frozen=True)
class MetricSpec:
    """The declared meaning of a metric, validated before any measurement."""

    name: str
    version: str
    lens: Lens
    granularity: UnitKind
    score_type: ScoreType
    direction: Direction
    evaluator_ref: str
    score_range: tuple[float, float] | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    required_evidence: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    aggregation: Aggregation = Aggregation.MEAN
    emits: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.score_type is ScoreType.CONTINUOUS and self.score_range is None:
            raise ContractError(
                f"metric '{self.name}': a continuous metric must declare a score_range"
            )
        if self.score_range is not None:
            low, high = self.score_range
            if low >= high:
                raise ContractError(
                    f"metric '{self.name}': score_range low ({low}) must be < high ({high})"
                )
        if not self.emits:
            object.__setattr__(self, "emits", [self.name])

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "lens": self.lens.value,
            "granularity": self.granularity.value,
            "score_type": self.score_type.value,
            "direction": self.direction.value,
            "evaluator_ref": self.evaluator_ref,
            "aggregation": self.aggregation.value,
            "emits": list(self.emits),
        }
        if self.score_range is not None:
            out["score_range"] = [self.score_range[0], self.score_range[1]]
        if self.profile:
            out["profile"] = dict(self.profile)
        if self.required_evidence:
            out["required_evidence"] = list(self.required_evidence)
        if self.prerequisites:
            out["prerequisites"] = list(self.prerequisites)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_spec_mapping(data)
        return cls(
            name=_require_str(m, "name", "MetricSpec"),
            version=_require_str(m, "version", "MetricSpec"),
            lens=_coerce_enum(Lens, _require(m, "lens", "MetricSpec"), "lens", "MetricSpec"),
            granularity=_coerce_enum(
                UnitKind, _require(m, "granularity", "MetricSpec"), "granularity", "MetricSpec"
            ),
            score_type=_coerce_enum(
                ScoreType, _require(m, "score_type", "MetricSpec"), "score_type", "MetricSpec"
            ),
            direction=_coerce_enum(
                Direction, _require(m, "direction", "MetricSpec"), "direction", "MetricSpec"
            ),
            evaluator_ref=_require_str(m, "evaluator_ref", "MetricSpec"),
            score_range=_parse_range(m.get("score_range"), m.get("name")),
            profile=_opt_mapping(m, "profile", "MetricSpec"),
            required_evidence=_opt_str_list(m, "required_evidence", "MetricSpec"),
            prerequisites=_opt_str_list(m, "prerequisites", "MetricSpec"),
            aggregation=_coerce_enum(
                Aggregation,
                m.get("aggregation", Aggregation.MEAN.value),
                "aggregation",
                "MetricSpec",
            ),
            emits=_opt_str_list(m, "emits", "MetricSpec"),
        )


def _as_spec_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ContractError(f"MetricSpec: expected a mapping, got {type(data).__name__}")
    return data


def _parse_range(value: Any, name: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list | tuple)
        or len(value) != 2
        or not all(isinstance(x, int | float) and not isinstance(x, bool) for x in value)
    ):
        raise ContractError(f"metric {name!r}: score_range must be a [low, high] pair of numbers")
    low, high = float(value[0]), float(value[1])
    if not (math.isfinite(low) and math.isfinite(high)):
        raise ContractError(f"metric {name!r}: score_range bounds must be finite (no NaN/inf)")
    return (low, high)


@dataclass
class MetricRegistry:
    """Holds validated metric specs and rejects unknown / undeclared score names."""

    _specs: dict[str, MetricSpec] = field(default_factory=dict)

    def register(self, spec: MetricSpec) -> None:
        if spec.name in self._specs:
            raise ContractError(f"metric '{spec.name}' is already registered")
        self._specs[spec.name] = spec

    def get(self, name: str) -> MetricSpec:
        if name not in self._specs:
            raise ContractError(f"unknown metric '{name}' (not registered)")
        return self._specs[name]

    def names(self) -> list[str]:
        return list(self._specs)

    def declares_score(self, score_name: str) -> bool:
        return any(score_name in spec.emits for spec in self._specs.values())

    def validate_emitted(self, score_name: str) -> None:
        if not self.declares_score(score_name):
            raise ContractError(
                f"score '{score_name}' is not declared by any registered metric "
                "(undeclared batch member)"
            )
