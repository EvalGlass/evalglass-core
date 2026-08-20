"""First-class per-metric population accounting (Epic D / D3).

Terminal counts are a verified projection of the raw scores (never a numeric zero for a
non-scored subject); the pre-effect coverage layer is plan-derived and stays unknown, never zero,
on a record that lacks it; and the reconciliation identities fail closed on a tampered count.
"""

from __future__ import annotations

import pytest

from evalglass.core import ContractError, Diagnostic, Score, ScoreStatus, Severity, Validity
from evalglass.core.population import PopulationSummary


def _score(metric: str, status: ScoreStatus, validity: Validity, value: float | None) -> Score:
    return Score(
        metric=metric,
        value=value,
        status=status,
        validity=validity,
        evaluator_version="t@1",
        diagnostics=[Diagnostic(code="c", severity=Severity.INFO, message="m")]
        if status is not ScoreStatus.SCORED
        else [],
    )


def test_terminal_counts_from_scores() -> None:
    scores = [
        _score("m", ScoreStatus.SCORED, Validity.VALID, 1.0),
        _score("m", ScoreStatus.SCORED, Validity.VALID, 0.0),
        _score("m", ScoreStatus.NON_EVALUABLE, Validity.NOT_APPLICABLE, None),
        _score("m", ScoreStatus.BLOCKED, Validity.NOT_MEASURED, None),
        _score("m", ScoreStatus.ERROR, Validity.NOT_MEASURED, None),
        _score("other", ScoreStatus.SCORED, Validity.VALID, 1.0),  # different metric, ignored
    ]
    pop = PopulationSummary.from_scores("m", scores)
    assert (pop.scored_valid, pop.non_evaluable, pop.blocked, pop.error) == (2, 1, 1, 1)
    assert pop.skipped == 0
    # Pre-effect coverage is unknown (plan-derived) — never fabricated as zero.
    assert pop.available is None
    assert pop.eligible is None


def test_scored_but_invalid_is_an_error_not_a_value() -> None:
    scores = [_score("m", ScoreStatus.SCORED, Validity.INVALID, 0.5)]
    pop = PopulationSummary.from_scores("m", scores)
    assert pop.scored_valid == 0
    assert pop.error == 1


def test_partial_evaluability_is_not_full_coverage() -> None:
    # 1 of 100 eligible scored -> not "fully evaluable".
    scores = [_score("m", ScoreStatus.SCORED, Validity.VALID, 1.0)]
    scores += [
        _score("m", ScoreStatus.NON_EVALUABLE, Validity.NOT_APPLICABLE, None) for _ in range(99)
    ]
    pop = PopulationSummary.from_scores("m", scores).with_plan_population(
        available=100,
        selector_matched=100,
        selector_excluded=0,
        eligible=100,
        prerequisite_excluded=0,
    )
    assert pop.scored_valid == 1
    assert pop.eligible == 100
    assert pop.measured is True
    assert pop.scored_valid < pop.eligible  # cannot render as fully evaluable


def test_pre_effect_reconciliation_identities_enforced() -> None:
    with pytest.raises(ContractError, match="selector_matched"):
        PopulationSummary(
            metric="m",
            scored_valid=1,
            non_evaluable=0,
            blocked=0,
            skipped=0,
            error=0,
            available=10,  # 10 != selector_matched(5) + selector_excluded(2) -> identity fails
            selector_matched=5,
            selector_excluded=2,
            eligible=5,
            prerequisite_excluded=0,
        )


def test_pre_effect_must_be_all_or_nothing() -> None:
    with pytest.raises(ContractError, match="all present or all unknown"):
        PopulationSummary(
            metric="m",
            scored_valid=1,
            non_evaluable=0,
            blocked=0,
            skipped=0,
            error=0,
            available=1,  # partial pre-effect
        )


def test_round_trip_with_and_without_pre_effect() -> None:
    terminal_only = PopulationSummary.from_scores(
        "m", [_score("m", ScoreStatus.SCORED, Validity.VALID, 1.0)]
    )
    assert PopulationSummary.from_dict(terminal_only.to_dict()) == terminal_only
    assert "available" not in terminal_only.to_dict()  # unknown pre-effect is omitted, not zeroed

    full = terminal_only.with_plan_population(
        available=3, selector_matched=2, selector_excluded=1, eligible=2, prerequisite_excluded=0
    )
    assert PopulationSummary.from_dict(full.to_dict()) == full
    assert full.to_dict()["available"] == 3


def test_negative_count_fails_closed() -> None:
    with pytest.raises(ContractError):
        PopulationSummary(
            metric="m", scored_valid=-1, non_evaluable=0, blocked=0, skipped=0, error=0
        )
