"""Score status, validity, and aggregation eligibility (EG-M0-2).

A measurement result separates *value* from *meaning*. The cardinal rule
(``CLAUDE.md §9``): a blocked, non-evaluable, skipped, or errored measurement is
not a low score and must never be encoded as ``0.0`` — it carries no value at all.
Only a ``scored`` + ``valid`` measurement holds a number and may enter numeric
aggregation. The non-scored states keep their diagnostics and evidence refs so
the reason is never erased.

Effect-free, stdlib-only (part of the Evaluation Core).
"""

from __future__ import annotations

import enum
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _as_mapping,
    _coerce_enum,
    _opt_list,
    _opt_mapping,
    _opt_str,
    _opt_str_list,
    _require,
    _require_str,
)
from evalglass.core.contracts import Diagnostic


class ScoreStatus(enum.StrEnum):
    SCORED = "scored"
    BLOCKED = "blocked"
    NON_EVALUABLE = "non_evaluable"
    SKIPPED = "skipped"
    ERROR = "error"


class Validity(enum.StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    NOT_MEASURED = "not_measured"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Score:
    """One metric result: value, status, validity, diagnostics, provenance."""

    metric: str
    value: float | None
    status: ScoreStatus
    validity: Validity
    evaluator_version: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    # Additive subject identity (F1 / ADR 0024): which Example/EvalUnit this score
    # measured. Additive provenance only — never metric meaning, authority, or a
    # per-source-function attribution. Optional for backward compatibility; the
    # harness/engine stamps it (evaluators need not), and ``view --by-call`` groups
    # by these explicit fields, never by score order.
    example_id: str | None = None
    unit_id: str | None = None

    def __post_init__(self) -> None:
        if self.status is ScoreStatus.SCORED:
            # bool is an int subclass but is not a meaningful numeric score.
            if isinstance(self.value, bool) or not isinstance(self.value, int | float):
                raise ContractError(
                    f"a scored Score must carry a numeric value, got {self.value!r}"
                )
            # NaN/±inf are not strict-JSON-compatible and poison aggregation.
            if isinstance(self.value, float) and not math.isfinite(self.value):
                raise ContractError(f"a scored Score value must be finite, got {self.value!r}")
        elif self.value is not None:
            raise ContractError(
                f"a '{self.status.value}' Score must not carry a value (got {self.value!r}); "
                "a blocked/skipped/errored/non-evaluable measurement is not a low score "
                "and must never be encoded as a number — see CLAUDE.md §9"
            )

    @property
    def is_aggregatable(self) -> bool:
        """Only a scored + valid measurement may enter numeric aggregation."""
        return self.status is ScoreStatus.SCORED and self.validity is Validity.VALID

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "value": self.value,
            "status": self.status.value,
            "validity": self.validity.value,
            "evaluator_version": self.evaluator_version,
        }
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        if self.evidence_refs:
            out["evidence_refs"] = list(self.evidence_refs)
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        # Emitted only when present so an identity-less score serializes as before.
        if self.example_id is not None:
            out["example_id"] = self.example_id
        if self.unit_id is not None:
            out["unit_id"] = self.unit_id
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Score")
        status = _coerce_enum(ScoreStatus, _require(m, "status", "Score"), "status", "Score")
        validity = _coerce_enum(Validity, _require(m, "validity", "Score"), "validity", "Score")
        diagnostics = [
            Diagnostic.from_dict(_as_mapping(d, "Score.diagnostics"))
            for d in _opt_list(m, "diagnostics", "Score")
        ]
        return cls(
            metric=_require_str(m, "metric", "Score"),
            value=_require(m, "value", "Score"),
            status=status,
            validity=validity,
            evaluator_version=_require_str(m, "evaluator_version", "Score"),
            diagnostics=diagnostics,
            evidence_refs=_opt_str_list(m, "evidence_refs", "Score"),
            provenance=_opt_mapping(m, "provenance", "Score"),
            example_id=_opt_str(m, "example_id", "Score"),
            unit_id=_opt_str(m, "unit_id", "Score"),
        )


@dataclass(frozen=True)
class ScoreBatch:
    """Related scores from one evaluator invocation, sharing evidence."""

    evaluator: str
    scores: list[Score]
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.scores:
            raise ContractError("a ScoreBatch must contain at least one score")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "evaluator": self.evaluator,
            "scores": [s.to_dict() for s in self.scores],
        }
        if self.evidence_refs:
            out["evidence_refs"] = list(self.evidence_refs)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "ScoreBatch")
        scores_raw = _require(m, "scores", "ScoreBatch")
        if not isinstance(scores_raw, list):
            raise ContractError("ScoreBatch: field 'scores' must be a list")
        return cls(
            evaluator=_require_str(m, "evaluator", "ScoreBatch"),
            scores=[Score.from_dict(_as_mapping(s, "ScoreBatch.scores")) for s in scores_raw],
            evidence_refs=_opt_str_list(m, "evidence_refs", "ScoreBatch"),
        )


def aggregatable(scores: Iterable[Score]) -> list[Score]:
    """Return only the scores eligible for numeric aggregation (scored + valid)."""
    return [score for score in scores if score.is_aggregatable]
