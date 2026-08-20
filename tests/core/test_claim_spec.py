"""Tests for the optional ClaimSpec construct/validity record (M7 G10).

See src/evalglass/core/claim_spec.py, src/evalglass/core/results.py, docs/TETA_REDESIGN.md §2.
"""

from __future__ import annotations

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.claim_spec import ClaimSpec
from evalglass.core.results import Scorecard
from evalglass.core.verdict import Verdict, VerdictPayload


def _spec(**over: object) -> ClaimSpec:
    base: dict[str, object] = {
        "construct": "consumer-fairness of a dispute recommendation",
        "intended_use": "surface unfair outcomes for human review",
        "target_population": "UK retail-payment disputes, synthetic",
        "sampling_frame": "3 hand-authored workflow artifacts",
        "known_threats": ["small sample", "references authored by the same project"],
        "prohibited_extrapolations": ["real customer outcomes"],
        "reviewer": "compliance@example.com",
        "review_expires_at": "2027-01-01T00:00:00Z",
    }
    base.update(over)
    return ClaimSpec(**base)  # type: ignore[arg-type]


def test_round_trip() -> None:
    s = _spec(validity_evidence_refs=["docs/validity/fairness.md"])
    assert ClaimSpec.from_dict(s.to_dict()) == s


def test_minimal_round_trip() -> None:
    s = ClaimSpec(construct="c", intended_use="u", target_population="p", sampling_frame="f")
    assert ClaimSpec.from_dict(s.to_dict()) == s


def test_digest_is_field_sensitive() -> None:
    assert _spec().digest() == _spec().digest()
    assert _spec().digest() != _spec(construct="different construct").digest()


def test_is_expired_uses_supplied_now() -> None:
    s = _spec(review_expires_at="2026-01-01T00:00:00Z")
    assert s.is_expired("2026-07-18T00:00:00Z")
    assert not s.is_expired("2025-06-01T00:00:00Z")
    assert not ClaimSpec(
        construct="c", intended_use="u", target_population="p", sampling_frame="f"
    ).is_expired("2099-01-01")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"construct": "  "},
        {"intended_use": ""},
        {"known_threats": "not-a-list"},
        {"known_threats": ["", "x"]},
        {"reviewer": "  "},
    ],
)
def test_invalid_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        _spec(**kwargs)


# --- Scorecard wiring ------------------------------------------------------


def _scorecard(**over: object) -> Scorecard:
    base: dict[str, object] = {
        "verdict": VerdictPayload(verdict=Verdict.INFORMATIONAL, ci_should_fail=False),
        "metrics": [],
        "authority": {},
    }
    base.update(over)
    return Scorecard(**base)  # type: ignore[arg-type]


def test_scorecard_without_claim_specs_omits_key() -> None:
    assert "claim_specs" not in _scorecard().to_dict()


def test_scorecard_with_claim_specs_round_trips() -> None:
    sc = _scorecard(claim_specs={"consumer_fairness": _spec()})
    d = sc.to_dict()
    assert "consumer_fairness" in d["claim_specs"]
    assert Scorecard.from_dict(d) == sc


def test_scorecard_malformed_claim_specs_fail_closed() -> None:
    d = _scorecard().to_dict()
    d["claim_specs"] = {"m": {"construct": "c"}}  # missing required fields
    with pytest.raises(ContractError):
        Scorecard.from_dict(d)
