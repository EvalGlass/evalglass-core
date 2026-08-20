"""Slice 4 (SG-P0-4): status aggregation + outputs.

The single status engine of the scan gate. Proves the matrix:
clean -> PASS, warn-only -> WARN, a fail finding -> FAIL, a blocked reason or a
failed/timed-out tool -> BLOCKED, and BLOCKED outranks FAIL (an incomplete scan
is never reported as merely a concrete failure, and never as PASS/WARN).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.contracts import Finding, ScanResult, Severity, Status, ToolLedgerEntry
from scripts.result_builder import aggregate_status, build_result, render_markdown, write_outputs

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = SKILL_ROOT / "schemas"


def _finding(severity: Severity, rule_id: str = "r") -> Finding:
    return Finding(
        id=f"SG-{rule_id}",
        rule_id=rule_id,
        severity=severity,
        surface="required-tier",
        evidence="e",
        tool="semgrep",
        tool_version="1",
        policy_version="p@1",
        recommendation="fix",
        file="src/evalglass/core/x.py",
        line=3,
    )


def test_clean_is_pass() -> None:
    assert aggregate_status([], []) is Status.PASS


def test_warn_only_is_warn() -> None:
    assert aggregate_status([_finding(Severity.WARN)], []) is Status.WARN


def test_info_only_is_pass() -> None:
    assert aggregate_status([_finding(Severity.INFO)], []) is Status.PASS


def test_fail_is_fail() -> None:
    assert aggregate_status([_finding(Severity.FAIL), _finding(Severity.WARN)], []) is Status.FAIL


def test_blocked_reason_is_blocked() -> None:
    assert aggregate_status([], ["semgrep timed out"]) is Status.BLOCKED


def test_block_severity_is_blocked() -> None:
    assert aggregate_status([_finding(Severity.BLOCK)], []) is Status.BLOCKED


def test_blocked_outranks_fail() -> None:
    status = aggregate_status(
        [_finding(Severity.FAIL)], ["classifier could not classify a high-risk path"]
    )
    assert status is Status.BLOCKED


def test_build_result_summary_counts() -> None:
    result = build_result(
        scan_id="EG.fast",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=7,
        findings=[_finding(Severity.FAIL), _finding(Severity.WARN), _finding(Severity.WARN)],
        tool_ledger=[],
        blocked_reasons=[],
    )
    assert result.status is Status.FAIL
    assert result.summary["files_scanned"] == 7
    assert result.summary["findings"] == 3
    assert result.summary["failures"] == 1
    assert result.summary["warnings"] == 2
    assert result.summary["blocked"] == 0


def test_failed_tool_ledger_forces_blocked() -> None:
    result = build_result(
        scan_id="EG.fast",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=1,
        findings=[_finding(Severity.FAIL)],
        tool_ledger=[
            ToolLedgerEntry(
                tool="gitleaks", version="8", network="disabled", adapter_status="timeout"
            )
        ],
        blocked_reasons=[],
    )
    assert result.status is Status.BLOCKED
    assert result.summary["blocked"] >= 1


def test_result_validates_against_schema_required_fields() -> None:
    result = build_result(
        scan_id="EG.fast",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=0,
        findings=[],
        tool_ledger=[],
        blocked_reasons=[],
    )
    payload = result.to_dict()
    required = set(json.loads((SCHEMAS / "scan-result.schema.json").read_text())["required"])
    assert required <= set(payload)
    assert ScanResult.from_dict(payload) == result


def test_markdown_renders_from_typed_data_without_claiming_final_status() -> None:
    result = build_result(
        scan_id="EG.fast",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=2,
        findings=[_finding(Severity.FAIL, "required.no_live_model_imports")],
        tool_ledger=[],
        blocked_reasons=[],
    )
    md = render_markdown(result)
    assert "FAIL" in md
    assert "required.no_live_model_imports" in md
    # Must not present itself as the final Execution Loop decision.
    assert "Synthesizer" in md or "evidence" in md.lower()


def test_markdown_escapes_untrusted_fields() -> None:
    nasty = Finding(
        id="SG-x",
        rule_id="r",
        severity=Severity.FAIL,
        surface="ci",
        evidence="bad | row\ninjection\n## heading",
        tool="t",
        tool_version="1",
        policy_version="p@1",
        recommendation="fix",
        file="a.sh",
        line=1,
    )
    result = build_result(
        scan_id="EG",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=1,
        findings=[nasty],
        tool_ledger=[],
        blocked_reasons=[],
    )
    md = render_markdown(result)
    # The evidence must not forge new table rows/headings or extra cells.
    assert "\n## heading" not in md
    assert sum(1 for line in md.splitlines() if line.startswith("| fail")) == 1
    row = next(line for line in md.splitlines() if line.startswith("| fail"))
    assert "\\|" in row  # the pipe inside evidence is escaped
    assert "injection" in row  # newlines collapsed into one cell
    assert "## heading" in row
    # Structural (unescaped) pipes only: 4 cells -> 5 pipes.
    assert row.count("|") - row.count("\\|") == 5


def test_write_outputs_emits_json_and_markdown(tmp_path: Path) -> None:
    result = build_result(
        scan_id="EG.fast",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=0,
        findings=[],
        tool_ledger=[],
        blocked_reasons=[],
    )
    jpath = tmp_path / "scan-gate.result.json"
    mpath = tmp_path / "scan-gate.summary.md"
    write_outputs(result, jpath, mpath)
    assert ScanResult.from_dict(json.loads(jpath.read_text())) == result
    assert mpath.read_text().strip() != ""


def test_write_outputs_creates_missing_parents(tmp_path: Path) -> None:
    result = build_result(
        scan_id="EG",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=0,
        findings=[],
        tool_ledger=[],
        blocked_reasons=[],
    )
    nested = tmp_path / "last-run" / "deep" / "scan-gate.result.json"
    md = tmp_path / "last-run" / "deep" / "scan-gate.summary.md"
    write_outputs(result, nested, md)  # parents do not exist yet
    assert nested.is_file()
    assert md.is_file()


def test_json_is_deterministic(tmp_path: Path) -> None:
    result = build_result(
        scan_id="EG.fast",
        profile_run="fast",
        policy_version="p@1",
        files_scanned=1,
        findings=[_finding(Severity.WARN, "a"), _finding(Severity.WARN, "b")],
        tool_ledger=[],
        blocked_reasons=[],
    )
    j1 = tmp_path / "a.json"
    j2 = tmp_path / "b.json"
    write_outputs(result, j1, None)
    write_outputs(result, j2, None)
    assert j1.read_text() == j2.read_text()
