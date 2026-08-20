"""First-class per-metric population accounting (Epic D / D3).

A single score surviving a run must never be confused with full coverage. ``PopulationSummary``
reconciles, for one metric, two layers by stable subject identity:

* the **pre-effect** population the ``EvaluationPlan`` resolved — how many subjects were *available*
  to the metric (its bound candidate sources), how many its selector *matched*, and how many were
  *eligible* after prerequisites — supplied by the Harness from the plan; and
* the **terminal** accounting derived purely from the raw ``Score`` s the metric emitted —
  ``scored_valid`` / ``non_evaluable`` / ``blocked`` / ``skipped`` / ``error``.

The terminal layer is a verified projection of the raw scores (the RunRecord recomputes it on load
and fails closed on a tampered count), so a blocked/non-evaluable/error subject can never be
laundered into a numeric zero or hidden behind a surviving score. The pre-effect layer is
plan-derived and is ``None`` ("unknown") for a legacy record or a core-only scorecard, never zero.

Terminal counts are over *emitted scores*, not subjects: a batch evaluator that emits several scores
for one subject, the synthetic selector-no-match score, and the run-integrity route-error score each
count once here. A ``scored`` measurement whose validity is not ``valid`` is counted as ``error``
(an invalid measurement is a measurement failure, not a value that enters the aggregate).
Effect-free, stdlib-only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import ContractError, _as_mapping, _require
from evalglass.core.scores import Score, ScoreStatus, Validity

#: The plan-derived pre-effect fields — ``None`` on a record that predates population accounting.
_PRE_EFFECT = (
    "available",
    "selector_matched",
    "selector_excluded",
    "eligible",
    "prerequisite_excluded",
)
#: The score-derived terminal fields — always known and anti-tamper verified against the raw scores.
_TERMINAL = ("scored_valid", "non_evaluable", "blocked", "skipped", "error")


@dataclass(frozen=True)
class PopulationSummary:
    """Per-metric evaluability accounting: pre-effect coverage + terminal measurement states."""

    metric: str
    # Terminal (score-derived, always known).
    scored_valid: int
    non_evaluable: int
    blocked: int
    skipped: int
    error: int
    # Pre-effect (plan-derived; None = unknown, e.g. a legacy record or a core-only scorecard).
    available: int | None = None
    selector_matched: int | None = None
    selector_excluded: int | None = None
    eligible: int | None = None
    prerequisite_excluded: int | None = None

    def __post_init__(self) -> None:
        for name in _TERMINAL:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractError(f"PopulationSummary: {name!r} must be a non-negative integer")
        for name in _PRE_EFFECT:
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ContractError(
                    f"PopulationSummary: {name!r} must be a non-negative integer or null"
                )
        # Pre-effect reconciliation identities, checked only when the plan-derived layer is present:
        # available splits into selector-matched + selector-excluded, and selector-matched splits
        # into eligible + prerequisite-excluded. A tampered pre-effect count breaks an identity.
        if self._pre_effect_present:
            if self.available != self.selector_matched + self.selector_excluded:  # type: ignore[operator]
                raise ContractError(
                    "PopulationSummary: available must equal selector_matched + selector_excluded"
                )
            if self.selector_matched != self.eligible + self.prerequisite_excluded:  # type: ignore[operator]
                raise ContractError(
                    "PopulationSummary: selector_matched must equal "
                    "eligible + prerequisite_excluded"
                )

    @property
    def _pre_effect_present(self) -> bool:
        present = [getattr(self, n) is not None for n in _PRE_EFFECT]
        if any(present) and not all(present):
            raise ContractError(
                "PopulationSummary: pre-effect counts must be all present or all unknown"
            )
        return all(present)

    @property
    def measured(self) -> bool:
        """Whether any subject reached a valid measurement (0/N scored is not measured)."""
        return self.scored_valid > 0

    @classmethod
    def from_scores(cls, metric: str, scores: Sequence[Score]) -> Self:
        """The terminal accounting for ``metric`` from its raw scores (pre-effect left unknown)."""
        own = [s for s in scores if s.metric == metric]
        counts = dict.fromkeys(_TERMINAL, 0)
        for score in own:
            counts[_terminal_bucket(score)] += 1
        return cls(metric=metric, **counts)

    def with_plan_population(
        self,
        *,
        available: int,
        selector_matched: int,
        selector_excluded: int,
        eligible: int,
        prerequisite_excluded: int,
    ) -> Self:
        """Return a copy enriched with the plan's pre-effect coverage (Harness-supplied)."""
        return type(self)(
            metric=self.metric,
            scored_valid=self.scored_valid,
            non_evaluable=self.non_evaluable,
            blocked=self.blocked,
            skipped=self.skipped,
            error=self.error,
            available=available,
            selector_matched=selector_matched,
            selector_excluded=selector_excluded,
            eligible=eligible,
            prerequisite_excluded=prerequisite_excluded,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"metric": self.metric}
        for name in _TERMINAL:
            out[name] = getattr(self, name)
        if self._pre_effect_present:
            for name in _PRE_EFFECT:
                out[name] = getattr(self, name)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "PopulationSummary")
        kwargs: dict[str, Any] = {"metric": str(_require(m, "metric", "PopulationSummary"))}
        for name in _TERMINAL:
            kwargs[name] = _require(m, name, "PopulationSummary")
        for name in _PRE_EFFECT:
            if name in m and m[name] is not None:
                kwargs[name] = m[name]
        return cls(**kwargs)


def _terminal_bucket(score: Score) -> str:
    """The terminal accounting bucket for one score (a scored-but-invalid score is an error)."""
    if score.status is ScoreStatus.SCORED:
        return "scored_valid" if score.validity is Validity.VALID else "error"
    return {
        ScoreStatus.NON_EVALUABLE: "non_evaluable",
        ScoreStatus.BLOCKED: "blocked",
        ScoreStatus.SKIPPED: "skipped",
        ScoreStatus.ERROR: "error",
    }[score.status]
