"""Slice 1 (SG-P0-1): contract + schema tests.

Proves: valid payloads round-trip; invalid status / severity rejected; missing
required field rejected; unknown extra keys tolerated (additive evolution); and
the shipped JSON Schemas stay consistent with the code enums/required fields
(consistency check, so no jsonschema dependency is needed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.contracts import (
    SCHEMA_VERSION_REQUEST,
    SCHEMA_VERSION_RESULT,
    ContractError,
    Finding,
    Profile,
    ScanRequest,
    ScanResult,
    Severity,
    Status,
    ToolLedgerEntry,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = SKILL_ROOT / "schemas"


def make_finding(**over: object) -> Finding:
    base: dict[str, object] = {
        "id": "SG-IMP-001",
        "rule_id": "required.no_live_model_imports",
        "severity": Severity.FAIL,
        "surface": "required-tier",
        "file": "src/evalglass/core/x.py",
        "line": 17,
        "evidence": "imports openai in a required-tier path",
        "tool": "semgrep",
        "tool_version": "1.2.3",
        "policy_version": "evalglass-scan-policy@2026-05-27",
        "recommendation": "Move live provider usage to an optional lane.",
    }
    base.update(over)
    return Finding(**base)  # type: ignore[arg-type]


def make_result(**over: object) -> ScanResult:
    base: dict[str, object] = {
        "scan_id": "EG.step-01.fast",
        "status": Status.PASS,
        "policy_version": "evalglass-scan-policy@2026-05-27",
        "profile_run": "fast",
    }
    base.update(over)
    return ScanResult(**base)  # type: ignore[arg-type]


def test_result_round_trip() -> None:
    r = make_result(status=Status.FAIL, findings=[make_finding()])
    payload = r.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION_RESULT
    assert ScanResult.from_dict(payload) == r


def test_result_json_serializable() -> None:
    json.dumps(make_result(findings=[make_finding()]).to_dict())


def test_request_round_trip() -> None:
    req = ScanRequest(
        scan_id="EG.step-01.fast",
        repo_root="/workspace",
        base_ref="origin/main",
        head_ref="HEAD",
        profile=Profile.FAST,
        policy_ref="policies/evalglass.fast.yml",
    )
    assert req.to_dict()["schema_version"] == SCHEMA_VERSION_REQUEST
    assert ScanRequest.from_dict(req.to_dict()) == req


def test_invalid_status_rejected() -> None:
    bad = {**make_result().to_dict(), "status": "GREEN"}
    with pytest.raises(ContractError):
        ScanResult.from_dict(bad)


def test_invalid_severity_rejected() -> None:
    bad = {**make_finding().to_dict(), "severity": "nope"}
    with pytest.raises(ContractError):
        Finding.from_dict(bad)


def test_missing_required_field_rejected() -> None:
    payload = make_result().to_dict()
    del payload["scan_id"]
    with pytest.raises(ContractError):
        ScanResult.from_dict(payload)


def test_additive_unknown_key_tolerated() -> None:
    payload = {**make_result().to_dict(), "future_field": {"x": 1}}
    assert isinstance(ScanResult.from_dict(payload), ScanResult)


def test_missing_schema_version_rejected() -> None:
    payload = make_result().to_dict()
    del payload["schema_version"]
    with pytest.raises(ContractError):
        ScanResult.from_dict(payload)


def test_mismatched_schema_version_rejected() -> None:
    payload = {**make_result().to_dict(), "schema_version": "scan-gate.result.v2"}
    with pytest.raises(ContractError):
        ScanResult.from_dict(payload)


def test_request_mismatched_schema_version_rejected() -> None:
    req = ScanRequest(
        scan_id="x",
        repo_root="/r",
        base_ref="main",
        head_ref="HEAD",
        profile=Profile.FAST,
        policy_ref="p.yml",
    )
    payload = {**req.to_dict(), "schema_version": "scan-gate.request.v9"}
    with pytest.raises(ContractError):
        ScanRequest.from_dict(payload)


def test_invalid_tool_ledger_network_rejected() -> None:
    with pytest.raises(ContractError):
        ToolLedgerEntry(tool="t", version="1", network="enabledx", adapter_status="completed")


def test_invalid_tool_ledger_adapter_status_rejected() -> None:
    with pytest.raises(ContractError):
        ToolLedgerEntry(tool="t", version="1", network="disabled", adapter_status="done")


def test_tool_ledger_entry_round_trip() -> None:
    entry = ToolLedgerEntry(
        tool="gitleaks",
        version="8.18.0",
        network="disabled",
        adapter_status="completed",
        exit_code=0,
        findings_count=0,
    )
    assert ToolLedgerEntry.from_dict(entry.to_dict()) == entry


def test_schema_files_are_valid_json_2020_12() -> None:
    for name in ("scan-request.schema.json", "scan-result.schema.json"):
        data = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        assert "2020-12" in data["$schema"]


def test_schema_status_enum_matches_code() -> None:
    data = json.loads((SCHEMAS / "scan-result.schema.json").read_text(encoding="utf-8"))
    assert set(data["properties"]["status"]["enum"]) == {s.value for s in Status}


def test_schema_result_required_matches_code() -> None:
    data = json.loads((SCHEMAS / "scan-result.schema.json").read_text(encoding="utf-8"))
    assert set(data["required"]) == set(ScanResult.required_fields())
