"""Slice 13 (VG-P3-2): seeded semantic bad-case suite — the credibility test.

Each seeded evidence pack trips exactly one family's headline violation and is
run through the real product path (``run_adapter``). Every case declares the
expected family id and the expected status; a meta-test fails if a family is
silently disabled, and a green-evidence case proves an unrelated PASS cannot
rescue a violation. BLOCKED cases are kept distinct from FAIL cases.
"""

from __future__ import annotations

import pytest

from scripts.adapter import run_adapter
from scripts.contracts import Status

_BUCKET = {
    "product": "product",
    "egts": "egts",
    "external": "external_contracts",
    "generated_or_proposed": "generated_or_proposed",
    "scan_gate": "scan_gate",
    "validator_gate": "validator_gate",
    "execution_loop": "execution_loop",
}


def pack(claim: dict, artifacts: list[dict], **extra) -> dict:
    boundary: dict[str, list[str]] = {}
    for a in artifacts:
        boundary.setdefault(_BUCKET[a["authority"]], []).append(a["id"])
    base = {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-13.seeded",
        "source_boundary": boundary,
        "claims": [claim],
        "artifacts": artifacts,
    }
    base.update(extra)
    return base


def claim(family: str, required: list[str], surfaces: list[str] | None = None) -> dict:
    return {
        "id": "c1",
        "text": f"seeded {family} claim",
        "expected_families": [family],
        "risk_surfaces": surfaces or [],
        "required_artifacts": required,
    }


def art(art_id, authority, kind, content) -> dict:
    return {"id": art_id, "authority": authority, "kind": kind, "content": content}


# (id, pack, expected_status, expected_family, mode)
#   mode: "fail" -> a FAIL finding from expected_family
#         "family_block" -> a BLOCKED finding from expected_family
#         "evidence_block" -> an evidence-level block (blocked_on), status BLOCKED
CASES = [
    (
        "duplicate_verdict_authority",
        pack(
            claim("authority_verdict", ["v1", "v2"]),
            [
                art("v1", "product", "verdict", {"verdict": "pass", "decides_verdict": True}),
                art("v2", "product", "verdict", {"verdict": "pass", "decides_verdict": True}),
            ],
        ),
        Status.FAIL,
        "authority_verdict",
        "fail",
    ),
    (
        "report_overclaim",
        pack(
            claim("authority_verdict", ["sc", "rep"]),
            [
                art("sc", "product", "scorecard", {"verdict": "blocked"}),
                art("rep", "external", "report", {"claimed_status": "pass"}),
            ],
        ),
        Status.FAIL,
        "authority_verdict",
        "fail",
    ),
    (
        "ci_overrides_product_verdict",
        pack(
            claim("authority_verdict", ["sc", "ci"]),
            [
                art("sc", "product", "scorecard", {"verdict": "blocked"}),
                art(
                    "ci",
                    "scan_gate",
                    "scan_result",
                    {"decides_verdict": True, "claimed_status": "pass"},
                ),
            ],
        ),
        Status.FAIL,
        "authority_verdict",
        "fail",
    ),
    (
        "egts_checker_computes_verdict",
        pack(
            claim("scenario_checker", ["scn", "chk"]),
            [
                art(
                    "scn",
                    "egts",
                    "scenario",
                    {"authored_expectation": "x", "scenario_version": "v1"},
                ),
                art("chk", "egts", "checker_output", {"decides_verdict": True}),
            ],
        ),
        Status.FAIL,
        "scenario_checker",
        "fail",
    ),
    (
        "scenario_accepts_emitted_output",
        pack(
            claim("scenario_checker", ["scn"]),
            [
                art(
                    "scn",
                    "egts",
                    "scenario",
                    {
                        "authored_expectation": "x",
                        "scenario_version": "v1",
                        "derived_from_output": True,
                    },
                )
            ],
        ),
        Status.FAIL,
        "scenario_checker",
        "fail",
    ),
    (
        "generated_artifact_promoted",
        pack(
            claim("contract_boundary", ["gen"]),
            [art("gen", "generated_or_proposed", "scorecard", {"promoted": True})],
        ),
        Status.FAIL,
        "contract_boundary",
        "fail",
    ),
    (
        "missing_baseline_for_regression",
        pack(
            claim("evidence_provenance", ["run"], surfaces=["regression"]),
            [art("run", "product", "run_record", {"timestamp": 100})],
        ),
        Status.BLOCKED,
        "evidence_provenance",
        "family_block",
    ),
    (
        "derived_artifact_without_provenance",
        pack(
            claim("evidence_provenance", ["d"]),
            [art("d", "product", "diagnostic", {"derived": True})],
        ),
        Status.FAIL,
        "evidence_provenance",
        "fail",
    ),
    (
        "hidden_input_backs_reproducible",
        pack(
            claim("integration_boundary", ["route"], surfaces=["reproducibility"]),
            [art("route", "external", "trace", {"runtime_route": "x", "hidden_input": True})],
        ),
        Status.FAIL,
        "integration_boundary",
        "fail",
    ),
    (
        "optional_lane_treated_as_required",
        pack(
            claim("integration_boundary", ["lane"]),
            [
                art(
                    "lane",
                    "external",
                    "trace",
                    {"lane": "ragas", "optional": True, "treated_as_required": True},
                )
            ],
        ),
        Status.FAIL,
        "integration_boundary",
        "fail",
    ),
    (
        "vendored_logic_as_authority",
        pack(
            claim("integration_boundary", ["vend"]),
            [art("vend", "external", "trace", {"vendored": True, "treated_as_original": True})],
        ),
        Status.FAIL,
        "integration_boundary",
        "fail",
    ),
    (
        "undeclared_judge_rag_influence",
        pack(
            claim("integration_boundary", ["rag"], surfaces=["rag"]),
            [art("rag", "external", "trace", {"rag": True})],
        ),
        Status.BLOCKED,
        "integration_boundary",
        "family_block",
    ),
    (
        "missing_scan_prerequisite",
        pack(
            claim("authority_verdict", ["sc", "scan_gate_result"]),
            [art("sc", "product", "scorecard", {"verdict": "pass"})],
        ),
        Status.BLOCKED,
        "authority_verdict",
        "evidence_block",
    ),
]

EXPECTED_FAMILIES = {
    "contract_boundary",
    "authority_verdict",
    "evidence_provenance",
    "scenario_checker",
    "integration_boundary",
}


@pytest.mark.parametrize(
    ("name", "evidence_pack", "status", "family", "mode"), CASES, ids=[c[0] for c in CASES]
)
def test_seeded_bad_case(
    name: str, evidence_pack: dict, status: Status, family: str, mode: str
) -> None:
    result, _ = run_adapter(evidence_pack)
    assert result.status is status, (
        f"{name}: expected {status}, got {result.status} ({result.blocked_on})"
    )
    if mode == "fail":
        assert any(
            f.family_id.value == family and f.status is Status.FAIL for f in result.findings
        ), (
            f"{name}: expected a FAIL finding from {family}; "
            f"findings={[(f.family_id.value, f.status.value) for f in result.findings]}"
        )
    elif mode == "family_block":
        assert any(
            f.family_id.value == family and f.status is Status.BLOCKED for f in result.findings
        ), f"{name}: expected a BLOCKED finding from {family}"
    else:  # evidence_block
        assert result.blocked_on, f"{name}: expected an evidence-level block"


def test_every_family_has_a_seeded_violation() -> None:
    # A silently-disabled family would leave a gap here.
    families_with_fail = {family for _, _, status, family, mode in CASES if mode == "fail"}
    assert families_with_fail >= EXPECTED_FAMILIES


def test_blocked_and_fail_cases_are_distinct() -> None:
    statuses = {name: status for name, _, status, _, _ in CASES}
    assert Status.FAIL in statuses.values()
    assert Status.BLOCKED in statuses.values()


def test_green_evidence_cannot_rescue_a_violation() -> None:
    # Attach an unrelated clean scan result to the overclaim case; still FAIL.
    overclaim = next(c for c in CASES if c[0] == "report_overclaim")[1]
    rescued = {**overclaim, "scan_gate_result": {"status": "PASS"}}
    result, _ = run_adapter(rescued)
    assert result.status is Status.FAIL
