"""Slice 1 (VG-P0-1): contract + schema tests.

Proves: valid payloads round-trip; invalid status / family id / authority /
artifact kind rejected; missing required field rejected; unknown extra keys
tolerated (additive evolution); schema_version enforced; the status precedence
helper encodes FAIL > BLOCKED > PASS_WITH_WARNINGS > PASS; and the shipped JSON
Schemas stay consistent with the code enums/required fields (consistency check,
so no jsonschema dependency is needed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.contracts import (
    SCHEMA_VERSION_EVIDENCE,
    SCHEMA_VERSION_RESULT,
    ArtifactKind,
    ArtifactRef,
    Authority,
    Claim,
    ContractError,
    EvidencePack,
    FamilyFinding,
    FamilyId,
    RouterFamily,
    RouterResult,
    Status,
    ValidatorResult,
    worst_status,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = SKILL_ROOT / "schemas"


# --- builders ---------------------------------------------------------------


def make_artifact(**over: object) -> ArtifactRef:
    base: dict[str, object] = {
        "id": "scorecard-1",
        "kind": ArtifactKind.SCORECARD,
        "authority": Authority.PRODUCT,
        "path": "evals/reports/scorecard.json",
        "content": {"verdict": "pass"},
        "produced_by": "evalglass",
        "claim_ids": ["claim-1"],
        "stale": False,
        "notes": None,
    }
    base.update(over)
    return ArtifactRef(**base)  # type: ignore[arg-type]


def make_claim(**over: object) -> Claim:
    base: dict[str, object] = {
        "id": "claim-1",
        "text": "The published report status equals the product verdict.",
        "risk_surfaces": ["verdict", "public_report"],
        "expected_families": [FamilyId.AUTHORITY_VERDICT],
        "required_artifacts": ["scorecard-1", "report-1"],
    }
    base.update(over)
    return Claim(**base)  # type: ignore[arg-type]


def make_finding(**over: object) -> FamilyFinding:
    base: dict[str, object] = {
        "family_id": FamilyId.AUTHORITY_VERDICT,
        "claim_id": "claim-1",
        "status": Status.FAIL,
        "evidence_refs": ["scorecard-1", "report-1"],
        "reason": "Report status claims pass while the product scorecard is blocked.",
        "remediation": "Make the report status reflect the product verdict payload.",
        "risk_ref": "report_public_surface",
    }
    base.update(over)
    return FamilyFinding(**base)  # type: ignore[arg-type]


def make_pack(**over: object) -> EvidencePack:
    base: dict[str, object] = {
        "checkpoint": "EG.step-07.authority",
        "source_boundary": {
            "product": ["scorecard-1"],
            "egts": [],
            "execution_loop": [],
            "scan_gate": [],
            "validator_gate": [],
            "generated_or_proposed": [],
            "external_contracts": ["report-1"],
        },
        "claims": [make_claim()],
        "artifacts": [make_artifact()],
    }
    base.update(over)
    return EvidencePack(**base)  # type: ignore[arg-type]


def make_result(**over: object) -> ValidatorResult:
    base: dict[str, object] = {
        "status": Status.PASS,
        "checkpoint": "EG.step-07.authority",
    }
    base.update(over)
    return ValidatorResult(**base)  # type: ignore[arg-type]


# --- round trips ------------------------------------------------------------


def test_result_round_trip() -> None:
    r = make_result(
        status=Status.FAIL, findings=[make_finding()], families_run=["authority_verdict"]
    )
    payload = r.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION_RESULT
    assert payload["gate"] == "validator"
    assert ValidatorResult.from_dict(payload) == r


def test_result_json_serializable() -> None:
    json.dumps(make_result(findings=[make_finding()]).to_dict())


def test_evidence_pack_round_trip() -> None:
    pack = make_pack()
    payload = pack.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION_EVIDENCE
    assert EvidencePack.from_dict(payload) == pack


def test_evidence_pack_json_serializable() -> None:
    json.dumps(make_pack().to_dict())


def test_artifact_ref_round_trip() -> None:
    a = make_artifact()
    assert ArtifactRef.from_dict(a.to_dict()) == a


def test_claim_round_trip() -> None:
    c = make_claim()
    assert Claim.from_dict(c.to_dict()) == c


def test_family_finding_round_trip() -> None:
    f = make_finding()
    assert FamilyFinding.from_dict(f.to_dict()) == f


def test_router_result_round_trip() -> None:
    rr = RouterResult(
        status=Status.PASS,
        families=[
            RouterFamily(family_id=FamilyId.AUTHORITY_VERDICT, claim_ids=["claim-1"], reason="x")
        ],
    )
    assert RouterResult.from_dict(rr.to_dict()) == rr


# --- invalid states ---------------------------------------------------------


def test_invalid_status_rejected() -> None:
    bad = {**make_result().to_dict(), "status": "GREEN"}
    with pytest.raises(ContractError):
        ValidatorResult.from_dict(bad)


def test_invalid_family_id_rejected() -> None:
    bad = {**make_finding().to_dict(), "family_id": "vibes_check"}
    with pytest.raises(ContractError):
        FamilyFinding.from_dict(bad)


def test_invalid_authority_rejected() -> None:
    bad = {**make_artifact().to_dict(), "authority": "vendor"}
    with pytest.raises(ContractError):
        ArtifactRef.from_dict(bad)


def test_invalid_artifact_kind_rejected() -> None:
    bad = {**make_artifact().to_dict(), "kind": "spreadsheet"}
    with pytest.raises(ContractError):
        ArtifactRef.from_dict(bad)


def test_missing_required_field_rejected_result() -> None:
    payload = make_result().to_dict()
    del payload["status"]
    with pytest.raises(ContractError):
        ValidatorResult.from_dict(payload)


def test_missing_required_field_rejected_pack() -> None:
    payload = make_pack().to_dict()
    del payload["checkpoint"]
    with pytest.raises(ContractError):
        EvidencePack.from_dict(payload)


def test_additive_unknown_key_tolerated() -> None:
    payload = {**make_result().to_dict(), "future_field": {"x": 1}}
    assert isinstance(ValidatorResult.from_dict(payload), ValidatorResult)
    pack = {**make_pack().to_dict(), "future_field": [1, 2, 3]}
    assert isinstance(EvidencePack.from_dict(pack), EvidencePack)


def test_missing_schema_version_rejected() -> None:
    payload = make_result().to_dict()
    del payload["schema_version"]
    with pytest.raises(ContractError):
        ValidatorResult.from_dict(payload)


def test_mismatched_schema_version_rejected_result() -> None:
    payload = {**make_result().to_dict(), "schema_version": "validator.result.v2"}
    with pytest.raises(ContractError):
        ValidatorResult.from_dict(payload)


def test_mismatched_schema_version_rejected_pack() -> None:
    payload = {**make_pack().to_dict(), "schema_version": "validator.evidence.v9"}
    with pytest.raises(ContractError):
        EvidencePack.from_dict(payload)


def test_foreign_gate_discriminator_rejected() -> None:
    # `gate` is a const discriminator: a stale/foreign result must fail closed.
    bad = {**make_result().to_dict(), "gate": "scan"}
    with pytest.raises(ContractError):
        ValidatorResult.from_dict(bad)


def test_families_run_must_be_known_family_ids() -> None:
    bad = {**make_result().to_dict(), "families_run": ["authority_verdict", "vibes_check"]}
    with pytest.raises(ContractError):
        ValidatorResult.from_dict(bad)


def test_evidence_pack_rejects_wrong_typed_collections() -> None:
    # Collection fields with wrong types must fail closed at the contract layer,
    # not raise AttributeError or be silently shredded (list("abc")).
    for mutation in (
        {"source_boundary": None},
        {"source_boundary": {"product": "scorecard-1"}},
        {"claims": None},
        {"artifacts": "nope"},
    ):
        with pytest.raises(ContractError):
            EvidencePack.from_dict({**make_pack().to_dict(), **mutation})


def test_claim_rejects_non_string_id_or_text() -> None:
    for mutation in ({"id": 1}, {"text": None}):
        with pytest.raises(ContractError):
            Claim.from_dict({**make_claim().to_dict(), **mutation})


def test_artifact_rejects_non_string_id() -> None:
    with pytest.raises(ContractError):
        ArtifactRef.from_dict({**make_artifact().to_dict(), "id": 7})


def test_router_status_must_be_pass_or_blocked() -> None:
    # Routing only succeeds or refuses; semantic FAIL/PWW come from findings.
    for impossible in (Status.FAIL, Status.PASS_WITH_WARNINGS):
        payload = {**RouterResult(status=Status.PASS).to_dict(), "status": impossible.value}
        with pytest.raises(ContractError):
            RouterResult.from_dict(payload)


def test_router_status_pass_and_blocked_accepted() -> None:
    for ok in (Status.PASS, Status.BLOCKED):
        rr = RouterResult.from_dict({"status": ok.value, "families": [], "blocked_on": []})
        assert rr.status is ok


# --- status precedence ------------------------------------------------------


def test_status_precedence_fail_beats_all() -> None:
    assert (
        worst_status([Status.PASS, Status.PASS_WITH_WARNINGS, Status.BLOCKED, Status.FAIL])
        is Status.FAIL
    )


def test_status_precedence_blocked_beats_warn_and_pass() -> None:
    assert worst_status([Status.PASS, Status.PASS_WITH_WARNINGS, Status.BLOCKED]) is Status.BLOCKED


def test_status_precedence_warn_beats_pass() -> None:
    assert worst_status([Status.PASS, Status.PASS_WITH_WARNINGS]) is Status.PASS_WITH_WARNINGS


def test_status_precedence_empty_is_pass() -> None:
    assert worst_status([]) is Status.PASS


def test_family_id_is_the_closed_five() -> None:
    assert {f.value for f in FamilyId} == {
        "contract_boundary",
        "authority_verdict",
        "evidence_provenance",
        "scenario_checker",
        "integration_boundary",
    }


# --- schema <-> code consistency (no jsonschema dependency) -----------------


def test_schema_files_are_valid_json_2020_12() -> None:
    for name in ("validator-evidence.schema.json", "validator-result.schema.json"):
        data = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        assert "2020-12" in data["$schema"]


def _result_schema() -> dict:
    return json.loads((SCHEMAS / "validator-result.schema.json").read_text(encoding="utf-8"))


def _evidence_schema() -> dict:
    return json.loads((SCHEMAS / "validator-evidence.schema.json").read_text(encoding="utf-8"))


def test_result_schema_status_enum_matches_code() -> None:
    assert set(_result_schema()["properties"]["status"]["enum"]) == {s.value for s in Status}


def test_result_schema_required_matches_code() -> None:
    assert set(_result_schema()["required"]) == set(ValidatorResult.required_fields())


def test_result_schema_family_id_enum_matches_code() -> None:
    # family_id (in findings) and families_run items both $ref this closed set.
    enum = _result_schema()["$defs"]["familyId"]["enum"]
    assert set(enum) == {f.value for f in FamilyId}
    assert _result_schema()["properties"]["families_run"]["items"]["$ref"] == "#/$defs/familyId"
    assert (
        _result_schema()["$defs"]["familyFinding"]["properties"]["family_id"]["$ref"]
        == "#/$defs/familyId"
    )


def test_evidence_schema_required_matches_code() -> None:
    assert set(_evidence_schema()["required"]) == set(EvidencePack.required_fields())


def test_evidence_schema_authority_enum_matches_code() -> None:
    enum = _evidence_schema()["$defs"]["artifactRef"]["properties"]["authority"]["enum"]
    assert set(enum) == {a.value for a in Authority}


def test_evidence_schema_kind_enum_matches_code() -> None:
    enum = _evidence_schema()["$defs"]["artifactRef"]["properties"]["kind"]["enum"]
    assert set(enum) == {k.value for k in ArtifactKind}
