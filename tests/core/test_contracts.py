"""Input/data public contracts — round-trip, invalid-state, route fidelity (EG-M0-1a).

These are the JSON-compatible boundary types the whole system shares. The tests
pin three properties the build contract requires (``architecture_build_contract.md``
§9, EG-M0-1): every contract round-trips through plain JSON; malformed data is
rejected (fail closed) rather than silently coerced; and the dataset/trace route
shapes (TraceEnvelope -> EvalUnit -> Example) stay distinct and are not conflated.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.contracts import (
    ContractError,
    DataPolicy,
    Diagnostic,
    EvalUnit,
    EvidenceBundle,
    Example,
    Severity,
    TraceEnvelope,
    UnitKind,
)


def _diag() -> Diagnostic:
    return Diagnostic(
        code="evaluator.parse_error",
        severity=Severity.ERROR,
        message="could not parse judge response",
        location="example=e1",
        evidence_refs=["judge:resp:1"],
    )


def _trace() -> TraceEnvelope:
    return TraceEnvelope(
        trace_id="t1",
        source="local_jsonl",
        behavior={"input": "2+2?", "output": "4"},
        data_policy=DataPolicy.PERMITTED,
        provenance={"adapter": "local_jsonl"},
    )


def _unit(kind: UnitKind = UnitKind.CALL) -> EvalUnit:
    return EvalUnit(unit_id="u1", kind=kind, trace_id="t1")


def _example() -> Example:
    return Example(example_id="e1", input="2+2?", output="4", reference="4", unit=_unit())


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(references=["4"], runtime_errors=[_diag()])


def _roundtrip[T](obj: T) -> T:
    """to_dict -> JSON -> from_dict, asserting JSON-compatibility on the way."""
    payload = obj.to_dict()  # type: ignore[attr-defined]
    text = json.dumps(payload)  # must be plain JSON-compatible data
    return type(obj).from_dict(json.loads(text))  # type: ignore[attr-defined, no-any-return]


# --- round-trip -------------------------------------------------------------


@pytest.mark.parametrize("obj", [_diag(), _trace(), _unit(), _example(), _evidence()])
def test_roundtrips_through_json(obj: object) -> None:
    assert _roundtrip(obj) == obj


def test_enums_serialize_as_plain_strings() -> None:
    payload = _trace().to_dict()
    assert payload["data_policy"] == "permitted"
    assert isinstance(payload["data_policy"], str)
    assert _diag().to_dict()["severity"] == "error"


def test_example_embeds_its_unit() -> None:
    payload = _example().to_dict()
    assert payload["unit"]["kind"] == "call"
    assert Example.from_dict(payload).unit.kind is UnitKind.CALL


# --- invalid state (fail closed) --------------------------------------------


@pytest.mark.parametrize("missing", ["code", "severity", "message"])
def test_diagnostic_missing_required_fails(missing: str) -> None:
    data = _diag().to_dict()
    del data[missing]
    with pytest.raises(ContractError):
        Diagnostic.from_dict(data)


def test_unknown_severity_fails() -> None:
    data = _diag().to_dict()
    data["severity"] = "catastrophic"
    with pytest.raises(ContractError):
        Diagnostic.from_dict(data)


@pytest.mark.parametrize("missing", ["trace_id", "source", "behavior", "data_policy"])
def test_trace_missing_required_fails(missing: str) -> None:
    data = _trace().to_dict()
    del data[missing]
    with pytest.raises(ContractError):
        TraceEnvelope.from_dict(data)


def test_unknown_data_policy_fails() -> None:
    data = _trace().to_dict()
    data["data_policy"] = "leak_everything"
    with pytest.raises(ContractError):
        TraceEnvelope.from_dict(data)


def test_unknown_unit_kind_fails() -> None:
    data = _unit().to_dict()
    data["kind"] = "quantum"
    with pytest.raises(ContractError):
        EvalUnit.from_dict(data)


def test_example_requires_unit() -> None:
    data = _example().to_dict()
    del data["unit"]
    with pytest.raises(ContractError):
        Example.from_dict(data)


def test_example_unit_must_be_a_mapping() -> None:
    data = _example().to_dict()
    data["unit"] = "u1"
    with pytest.raises(ContractError):
        Example.from_dict(data)


def test_evidence_rejects_malformed_runtime_error() -> None:
    data = _evidence().to_dict()
    data["runtime_errors"] = [{"message": "no code or severity"}]
    with pytest.raises(ContractError):
        EvidenceBundle.from_dict(data)


def test_non_mapping_payload_fails() -> None:
    with pytest.raises(ContractError):
        TraceEnvelope.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]


# --- route fidelity: the three shapes are distinct, not conflated -----------


def test_trace_unit_example_are_distinct_types() -> None:
    assert {type(_trace()), type(_unit()), type(_example())} == {
        TraceEnvelope,
        EvalUnit,
        Example,
    }


def test_a_trace_payload_is_not_a_valid_example() -> None:
    """The route must not let a TraceEnvelope masquerade as an Example."""
    with pytest.raises(ContractError):
        Example.from_dict(_trace().to_dict())


# --- unit kinds: call now; step/trajectory/session reserved -----------------


@pytest.mark.parametrize(
    "kind", [UnitKind.CALL, UnitKind.STEP, UnitKind.TRAJECTORY, UnitKind.SESSION]
)
def test_all_unit_kinds_round_trip(kind: UnitKind) -> None:
    assert _roundtrip(_unit(kind)).kind is kind
