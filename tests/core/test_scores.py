"""Score status, validity, and aggregation eligibility (EG-M0-2).

The cardinal rule: an invalid, blocked, non-evaluable, skipped, or errored
measurement is *not* a low score. Such states must never be encoded as ``0.0``
(``CLAUDE.md §9``); only a ``scored`` + ``valid`` measurement carries a number and
may enter numeric aggregation. Diagnostics and evidence refs survive on the
non-scored states so the reason is never erased.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.contracts import ContractError, Diagnostic, Severity
from evalglass.core.scores import Score, ScoreBatch, ScoreStatus, Validity, aggregatable


def _scored(value: float = 1.0, validity: Validity = Validity.VALID) -> Score:
    return Score(
        metric="exact_match",
        value=value,
        status=ScoreStatus.SCORED,
        validity=validity,
        evaluator_version="exact_match@1",
    )


def _blocked() -> Score:
    return Score(
        metric="faithfulness",
        value=None,
        status=ScoreStatus.BLOCKED,
        validity=Validity.NOT_MEASURED,
        evaluator_version="judge_faithfulness@1",
        diagnostics=[
            Diagnostic(
                code="blocked.missing_evidence",
                severity=Severity.ERROR,
                message="no judge evidence was supplied",
            )
        ],
        evidence_refs=["judge:faithfulness:missing"],
    )


def _with_identity() -> Score:
    return Score(
        metric="exact_match",
        value=1.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="exact_match@1",
        example_id="ex-007",
        unit_id="call-007",
    )


# --- round-trip + visibility ------------------------------------------------


@pytest.mark.parametrize("score", [_scored(), _blocked(), _with_identity()])
def test_score_round_trips(score: Score) -> None:
    assert Score.from_dict(json.loads(json.dumps(score.to_dict()))) == score


def test_status_and_validity_are_visible_in_payload() -> None:
    payload = _blocked().to_dict()
    assert payload["status"] == "blocked"
    assert payload["validity"] == "not_measured"
    assert payload["value"] is None


def test_blocked_preserves_diagnostics_and_evidence() -> None:
    restored = Score.from_dict(_blocked().to_dict())
    assert restored.diagnostics[0].code == "blocked.missing_evidence"
    assert restored.evidence_refs == ["judge:faithfulness:missing"]


# --- the cardinal rule: non-scored never carries a value --------------------


@pytest.mark.parametrize(
    "status",
    [ScoreStatus.BLOCKED, ScoreStatus.NON_EVALUABLE, ScoreStatus.SKIPPED, ScoreStatus.ERROR],
)
def test_non_scored_must_not_carry_a_value(status: ScoreStatus) -> None:
    with pytest.raises(ContractError):
        Score(
            metric="m",
            value=0.0,  # the exact false-confidence bug we forbid
            status=status,
            validity=Validity.NOT_MEASURED,
            evaluator_version="m@1",
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_scored_rejects_non_finite_value(bad: float) -> None:
    """NaN/±inf break strict JSON and poison aggregation — fail closed."""
    with pytest.raises(ContractError):
        Score(
            metric="m",
            value=bad,
            status=ScoreStatus.SCORED,
            validity=Validity.VALID,
            evaluator_version="m@1",
        )


def test_scored_requires_a_numeric_value() -> None:
    with pytest.raises(ContractError):
        Score(
            metric="m",
            value=None,
            status=ScoreStatus.SCORED,
            validity=Validity.VALID,
            evaluator_version="m@1",
        )


def test_scored_rejects_bool_value() -> None:
    """bool is an int subclass but is not a meaningful numeric score."""
    with pytest.raises(ContractError):
        Score(
            metric="m",
            value=True,  # bool is an int subclass; mypy allows it, the runtime guard rejects it
            status=ScoreStatus.SCORED,
            validity=Validity.VALID,
            evaluator_version="m@1",
        )


# --- aggregation eligibility ------------------------------------------------


def test_only_scored_and_valid_is_aggregatable() -> None:
    assert _scored(validity=Validity.VALID).is_aggregatable is True
    assert _scored(validity=Validity.INVALID).is_aggregatable is False
    assert _blocked().is_aggregatable is False


def test_aggregatable_filters_a_mixed_batch() -> None:
    scores = [
        _scored(value=1.0),
        _scored(value=0.0, validity=Validity.INVALID),  # measured but invalid
        _blocked(),
    ]
    eligible = aggregatable(scores)
    assert [s.value for s in eligible] == [1.0]


# --- invalid state (fail closed) --------------------------------------------


@pytest.mark.parametrize("missing", ["metric", "value", "status", "validity", "evaluator_version"])
def test_score_missing_required_fails(missing: str) -> None:
    data = _scored().to_dict()
    del data[missing]
    with pytest.raises(ContractError):
        Score.from_dict(data)


@pytest.mark.parametrize(("field", "bad"), [("status", "great"), ("validity", "truthy")])
def test_score_unknown_enum_fails(field: str, bad: str) -> None:
    data = _scored().to_dict()
    data[field] = bad
    with pytest.raises(ContractError):
        Score.from_dict(data)


# --- ScoreBatch -------------------------------------------------------------


def _batch() -> ScoreBatch:
    return ScoreBatch(
        evaluator="ragas@1",
        scores=[_scored(), _blocked()],
        evidence_refs=["judge:batch:1"],
    )


def test_score_batch_round_trips() -> None:
    assert ScoreBatch.from_dict(json.loads(json.dumps(_batch().to_dict()))) == _batch()


def test_empty_score_batch_fails() -> None:
    with pytest.raises(ContractError):
        ScoreBatch(evaluator="e@1", scores=[])


def test_score_batch_rejects_non_score_member() -> None:
    data = _batch().to_dict()
    data["scores"] = [{"not": "a score"}]
    with pytest.raises(ContractError):
        ScoreBatch.from_dict(data)


# --- F1: additive score subject identity (ADR 0024) -------------------------


def test_identity_defaults_to_none() -> None:
    s = _scored()
    assert s.example_id is None
    assert s.unit_id is None


def test_identity_is_emitted_only_when_present() -> None:
    """Additive: an identity-less score serializes exactly as before (no new keys)."""
    bare = _scored().to_dict()
    assert "example_id" not in bare
    assert "unit_id" not in bare
    stamped = _with_identity().to_dict()
    assert stamped["example_id"] == "ex-007"
    assert stamped["unit_id"] == "call-007"


def test_from_dict_accepts_old_record_without_identity() -> None:
    """Old runrecord.json scores (no identity) still parse — backward compatible."""
    old = {
        "metric": "exact_match",
        "value": 1.0,
        "status": "scored",
        "validity": "valid",
        "evaluator_version": "exact_match@1",
    }
    restored = Score.from_dict(old)
    assert restored.example_id is None
    assert restored.unit_id is None


def test_identity_round_trips_through_json() -> None:
    restored = Score.from_dict(json.loads(json.dumps(_with_identity().to_dict())))
    assert restored.example_id == "ex-007"
    assert restored.unit_id == "call-007"
    assert restored == _with_identity()


@pytest.mark.parametrize("field_name", ["example_id", "unit_id"])
@pytest.mark.parametrize("bad", [123, [], {}, 1.5, True])
def test_from_dict_rejects_non_string_identity(field_name: str, bad: object) -> None:
    """Fail closed: a present-but-non-string identity is a malformed artifact, not a guess."""
    data = _with_identity().to_dict()
    data[field_name] = bad
    with pytest.raises(ContractError):
        Score.from_dict(data)


def test_identity_flows_through_score_batch() -> None:
    batch = ScoreBatch(evaluator="ragas@1", scores=[_with_identity(), _blocked()])
    restored = ScoreBatch.from_dict(json.loads(json.dumps(batch.to_dict())))
    assert restored.scores[0].example_id == "ex-007"
    assert restored.scores[0].unit_id == "call-007"
    assert restored == batch


def test_identity_does_not_affect_aggregation_eligibility() -> None:
    """Subject identity is provenance, not meaning — it cannot change aggregatability."""
    assert _with_identity().is_aggregatable is True
    assert aggregatable([_with_identity(), _blocked()]) == [_with_identity()]
