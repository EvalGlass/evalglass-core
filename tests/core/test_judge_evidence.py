"""JudgeEvidence contract — round-trip, fail-closed, evidence-not-authority (EG-M4-1a).

``JudgeEvidence`` is the typed record of one judge invocation: collected by the
Runtime Harness (an effect) and parsed by the effect-free judge evaluator into a
``Score`` (EG-M4-4). It is *evidence, not authority* (CLAUDE.md §14): it never
carries a verdict, and — mirroring the cardinal score rule (§9) — a failed judge
call (timeout / provider error / missing / malformed response) carries **no**
parsed value. A timed-out judge is not a ``0.0``.

These are the S1a Layer-1 tests (tests-first): JSON round-trip, fail-closed
parsing of every field, the parsed-value-only-on-OK invariant, and the typed
``EvidenceBundle.judge_evidence`` it slots into. The EGTS contract-snapshot proof
of the same surface lands in EGTS-M4.
"""

from __future__ import annotations

import json

import pytest

import evalglass.core as core
from evalglass.core.contracts import (
    ContractError,
    Diagnostic,
    EvidenceBundle,
    JudgeEvidence,
    JudgeEvidenceStatus,
    Severity,
)

_FAILED = [
    JudgeEvidenceStatus.TIMEOUT,
    JudgeEvidenceStatus.PROVIDER_ERROR,
    JudgeEvidenceStatus.MALFORMED,
    JudgeEvidenceStatus.MISSING,
]


def _diag() -> Diagnostic:
    return Diagnostic(
        code="judge.parse_error",
        severity=Severity.ERROR,
        message="judge response was not parseable",
        location="example=e1;metric=faithfulness",
    )


def _ok() -> JudgeEvidence:
    """A fully-populated successful judge evidence record."""
    return JudgeEvidence(
        example_id="e1",
        metric="faithfulness",
        status=JudgeEvidenceStatus.OK,
        parsed_value=0.75,
        raw_response='{"score": 0.75, "reason": "grounded"}',
        rationale="grounded in the source",
        rubric_ref="rubrics/faithfulness.md",
        rubric_version="2",
        prompt_ref="prompts/faithfulness@1",
        model_ref="fake-judge-1",
        parser_version="json_score@1",
        response_fingerprint="sha256:abc",
        tokens=128,
        cost=0.0,
        latency_ms=12.5,
        provenance={"adapter": "judge_fake"},
    )


def _failed(status: JudgeEvidenceStatus) -> JudgeEvidence:
    """A failed judge call: status only, no value, with a diagnostic."""
    return JudgeEvidence(
        example_id="e1",
        metric="faithfulness",
        status=status,
        rubric_ref="rubrics/faithfulness.md",
        diagnostics=[_diag()],
    )


def _roundtrip[T](obj: T) -> T:
    payload = obj.to_dict()  # type: ignore[attr-defined]
    text = json.dumps(payload)  # must be plain JSON-compatible data
    return type(obj).from_dict(json.loads(text))  # type: ignore[attr-defined, no-any-return]


# --- round-trip -------------------------------------------------------------


@pytest.mark.parametrize(
    "obj",
    [
        _ok(),
        JudgeEvidence(example_id="e1", metric="m", status=JudgeEvidenceStatus.OK),
        *[_failed(s) for s in _FAILED],
    ],
)
def test_roundtrips_through_json(obj: JudgeEvidence) -> None:
    assert _roundtrip(obj) == obj


def test_status_serializes_as_plain_string() -> None:
    assert _ok().to_dict()["status"] == "ok"
    assert _failed(JudgeEvidenceStatus.TIMEOUT).to_dict()["status"] == "timeout"


def test_to_dict_omits_absent_optionals() -> None:
    payload = JudgeEvidence(
        example_id="e1", metric="m", status=JudgeEvidenceStatus.MISSING
    ).to_dict()
    assert payload == {"example_id": "e1", "metric": "m", "status": "missing"}
    for absent in ("parsed_value", "raw_response", "rationale", "tokens", "cost", "diagnostics"):
        assert absent not in payload


def test_diagnostics_round_trip_inside_judge_evidence() -> None:
    restored = _roundtrip(_failed(JudgeEvidenceStatus.MALFORMED))
    assert restored.diagnostics[0].code == "judge.parse_error"


# --- the cardinal invariant: a failed judge call is not a low score ---------


@pytest.mark.parametrize("status", _FAILED)
def test_failed_status_must_not_carry_parsed_value(status: JudgeEvidenceStatus) -> None:
    """A timeout/error/missing/malformed judge result must never smuggle a value."""
    with pytest.raises(ContractError):
        JudgeEvidence(example_id="e1", metric="m", status=status, parsed_value=0.0)


@pytest.mark.parametrize("status", _FAILED)
def test_failed_status_rejects_value_via_from_dict(status: JudgeEvidenceStatus) -> None:
    data = {"example_id": "e1", "metric": "m", "status": status.value, "parsed_value": 0.0}
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_parsed_value_must_be_finite(bad: float) -> None:
    with pytest.raises(ContractError):
        JudgeEvidence(example_id="e1", metric="m", status=JudgeEvidenceStatus.OK, parsed_value=bad)


def test_parsed_value_rejects_bool() -> None:
    # bool is an int subclass but is not a meaningful numeric score.
    with pytest.raises(ContractError):
        JudgeEvidence(
            example_id="e1",
            metric="m",
            status=JudgeEvidenceStatus.OK,
            parsed_value=True,
        )


def test_oversized_number_fails_closed() -> None:
    # a JSON integer too large to become a float must raise ContractError, not OverflowError.
    data = {"example_id": "e1", "metric": "m", "status": "ok", "parsed_value": 10**400}
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


def test_direct_construction_validates_cost() -> None:
    with pytest.raises(ContractError):
        JudgeEvidence(example_id="e1", metric="m", status=JudgeEvidenceStatus.OK, cost=float("inf"))


def test_direct_construction_validates_latency() -> None:
    with pytest.raises(ContractError):
        JudgeEvidence(
            example_id="e1", metric="m", status=JudgeEvidenceStatus.OK, latency_ms=float("nan")
        )


def test_direct_construction_rejects_bool_tokens() -> None:
    # construct/parse symmetry: from_dict rejects bool tokens, so must the constructor.
    with pytest.raises(ContractError):
        JudgeEvidence(example_id="e1", metric="m", status=JudgeEvidenceStatus.OK, tokens=True)


# --- fail-closed parsing ----------------------------------------------------


@pytest.mark.parametrize("missing", ["example_id", "metric", "status"])
def test_missing_required_fails(missing: str) -> None:
    data = _ok().to_dict()
    del data[missing]
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


def test_unknown_status_fails() -> None:
    data = _ok().to_dict()
    data["status"] = "hallucinated"
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


@pytest.mark.parametrize("field_name", ["parsed_value", "cost", "latency_ms"])
def test_numeric_fields_reject_strings(field_name: str) -> None:
    data = _ok().to_dict()
    data[field_name] = "0.5"
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


def test_tokens_rejects_non_integer() -> None:
    data = _ok().to_dict()
    data["tokens"] = 1.5
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


def test_tokens_rejects_bool() -> None:
    data = _ok().to_dict()
    data["tokens"] = True
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


def test_ref_fields_reject_non_strings() -> None:
    data = _ok().to_dict()
    data["rubric_ref"] = 7
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


def test_non_mapping_payload_fails() -> None:
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_malformed_diagnostic_fails() -> None:
    data = _failed(JudgeEvidenceStatus.MALFORMED).to_dict()
    data["diagnostics"] = [{"message": "no code or severity"}]
    with pytest.raises(ContractError):
        JudgeEvidence.from_dict(data)


# --- EvidenceBundle now carries typed JudgeEvidence -------------------------


def test_evidence_bundle_round_trips_typed_judge_evidence() -> None:
    bundle = EvidenceBundle(judge_evidence=[_ok(), _failed(JudgeEvidenceStatus.TIMEOUT)])
    restored = _roundtrip(bundle)
    assert restored == bundle
    assert all(isinstance(j, JudgeEvidence) for j in restored.judge_evidence)


def test_evidence_bundle_rejects_malformed_judge_evidence() -> None:
    data = EvidenceBundle(judge_evidence=[_ok()]).to_dict()
    # a failed judge result carrying a value must fail closed through the bundle too
    data["judge_evidence"] = [
        {"example_id": "e1", "metric": "m", "status": "timeout", "parsed_value": 0.0}
    ]
    with pytest.raises(ContractError):
        EvidenceBundle.from_dict(data)


# --- public surface ---------------------------------------------------------


def test_judge_evidence_is_public() -> None:
    assert core.JudgeEvidence is JudgeEvidence
    assert core.JudgeEvidenceStatus is JudgeEvidenceStatus
    assert "JudgeEvidence" in core.__all__
    assert "JudgeEvidenceStatus" in core.__all__
