"""Structured rubric contract + structured judge-response parser (ADR 0053).

Proves the typed rubric: anchored criteria, a declared response schema, a content digest that turns
on score-determining content (not review status), markdown compatibility, and round-trip. Then the
parser: it distinguishes a valid score from refusal / missing evidence / parser error, rejects an
undeclared facet, resolves cited evidence refs against the bounded dossier, and never emits a score
for a non-OK outcome. Fixtures are domain-neutral.
"""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.core._validation import ContractError
from evalglass.harness.rubric_spec import (
    CriterionType,
    ParsedResponseStatus,
    RubricCriterion,
    RubricSpec,
    RubricStatus,
    parse_judge_response,
)

_SPEC: dict[str, Any] = {
    "schema": "evalglass.rubric/1",
    "construct": "How well is each claim supported by the provided source?",
    "criteria": [
        {
            "name": "support",
            "output_type": "score",
            "anchors": {"1.0": "every claim grounded", "0.0": "a central claim unsupported"},
        },
        {"name": "has_citation", "output_type": "boolean"},
    ],
    "evidence_layers": ["input", "output", "reference"],
    "response": {"facets": ["support", "has_citation"], "allow_citations": True},
    "version": "1",
}


def _spec(**overrides: Any) -> RubricSpec:
    return RubricSpec.from_mapping({**_SPEC, **overrides})


# --------------------------------------------------------------------------- #
# Contract: parse / round-trip / fail-closed
# --------------------------------------------------------------------------- #


def test_structured_rubric_parses_and_round_trips() -> None:
    spec = _spec()
    assert spec.construct.startswith("How well")
    assert [c.name for c in spec.criteria] == ["support", "has_citation"]
    assert spec.is_structured
    assert spec.status is RubricStatus.PROPOSED  # new rubric is proposed until reviewed
    assert RubricSpec.from_mapping(spec.to_dict()) == spec


def test_missing_construct_is_a_setup_error() -> None:
    data = {k: v for k, v in _SPEC.items() if k != "construct"}
    with pytest.raises(ContractError):
        RubricSpec.from_mapping(data)


def test_unknown_schema_is_refused() -> None:
    with pytest.raises(ContractError):
        _spec(schema="evalglass.rubric/9")


def test_score_criterion_without_anchors_is_refused() -> None:
    # AC2: every criterion must be anchored or have an explicit non-score output type.
    with pytest.raises(ContractError):
        RubricCriterion(name="fluency", output_type=CriterionType.SCORE)


def test_response_facet_not_a_declared_criterion_is_refused() -> None:
    with pytest.raises(ContractError):
        _spec(response={"facets": ["support", "not_a_criterion"]})


def test_duplicate_criterion_names_are_refused() -> None:
    with pytest.raises(ContractError):
        _spec(
            criteria=[
                {"name": "support", "output_type": "boolean"},
                {"name": "support", "output_type": "boolean"},
            ],
            response={"facets": ["support"]},
        )


# --------------------------------------------------------------------------- #
# Digest: turns on score-determining content, not review status
# --------------------------------------------------------------------------- #


def test_digest_changes_when_construct_or_criteria_change() -> None:
    base = _spec().content_digest()
    assert _spec(construct="A different construct entirely").content_digest() != base
    assert _spec(version="2").content_digest() != base
    assert _spec(parser_version="2").content_digest() != base


def test_reviewing_a_rubric_does_not_change_its_digest() -> None:
    # Review status must not affect comparability — it does not change what the rubric measures.
    proposed = _spec(status="proposed").content_digest()
    reviewed = _spec(status="reviewed").content_digest()
    assert proposed == reviewed


# --------------------------------------------------------------------------- #
# Markdown compatibility (the scalar score+rationale rubric)
# --------------------------------------------------------------------------- #


def test_markdown_rubric_loads_as_unanchored_construct_without_facets() -> None:
    spec = RubricSpec.from_markdown("Score how faithful the answer is to the source.")
    assert not spec.is_structured  # no facets -> scalar score+rationale contract
    assert spec.criteria == ()
    assert "faithful" in spec.construct


# --------------------------------------------------------------------------- #
# Parser: valid / refusal / missing / error
# --------------------------------------------------------------------------- #


def test_parser_accepts_a_valid_structured_response() -> None:
    spec = _spec()
    result = parse_judge_response(
        {
            "score": 0.75,
            "rationale": "mostly grounded",
            "facets": {"support": 0.8, "has_citation": True},
            "citations": ["EVID_1"],
        },
        spec,
        dossier_refs=frozenset({"EVID_1"}),
    )
    assert result.status is ParsedResponseStatus.OK
    assert result.score == pytest.approx(0.75)
    assert result.facets_dict() == {"support": pytest.approx(0.8), "has_citation": True}
    assert result.citations == ("EVID_1",)


def test_parser_reports_refusal_without_a_score() -> None:
    result = parse_judge_response({"refusal": "the source is unreadable"}, _spec())
    assert result.status is ParsedResponseStatus.REFUSED
    assert result.score is None
    assert result.refusal_reason == "the source is unreadable"


def test_parser_reports_missing_evidence_without_a_score() -> None:
    result = parse_judge_response({"missing_evidence": True}, _spec())
    assert result.status is ParsedResponseStatus.MISSING_EVIDENCE
    assert result.score is None


@pytest.mark.parametrize(
    "payload",
    [
        {"rationale": "no score here"},  # no score
        {"score": "high"},  # non-numeric
        {"score": float("nan")},  # non-finite
        "not an object",  # not a JSON object
    ],
)
def test_parser_reports_a_parser_error_without_a_score(payload: Any) -> None:
    result = parse_judge_response(payload, _spec())
    assert result.status is ParsedResponseStatus.PARSER_ERROR
    assert result.score is None


def test_parser_rejects_an_undeclared_facet() -> None:
    # AC2: a facet the rubric never declared is a parser error, not silently accepted.
    result = parse_judge_response(
        {"score": 0.5, "facets": {"support": 0.5, "invented": 1.0}}, _spec()
    )
    assert result.status is ParsedResponseStatus.PARSER_ERROR
    assert "invented" in (result.message or "")


def test_parser_rejects_an_unresolvable_citation() -> None:
    # AC4: an invented citation that resolves nowhere in the dossier is diagnosed.
    result = parse_judge_response(
        {"score": 0.9, "citations": ["EVID_DOES_NOT_EXIST"]},
        _spec(),
        dossier_refs=frozenset({"EVID_1"}),
    )
    assert result.status is ParsedResponseStatus.PARSER_ERROR
    assert "EVID_DOES_NOT_EXIST" in (result.message or "")


def test_parser_rejects_a_wrong_typed_facet() -> None:
    result = parse_judge_response(
        {"score": 0.5, "facets": {"has_citation": "yes"}},  # boolean facet given a string
        _spec(),
    )
    assert result.status is ParsedResponseStatus.PARSER_ERROR


def test_required_citation_missing_is_an_error() -> None:
    spec = _spec(response={"facets": ["support"], "require_citations": True})
    result = parse_judge_response({"score": 0.9}, spec, dossier_refs=frozenset({"EVID_1"}))
    assert result.status is ParsedResponseStatus.PARSER_ERROR


def test_parser_clamps_out_of_range_score() -> None:
    result = parse_judge_response({"score": 1.4}, _spec())
    assert result.status is ParsedResponseStatus.OK
    assert result.score == pytest.approx(1.0)
