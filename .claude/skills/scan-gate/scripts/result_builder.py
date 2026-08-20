"""Status aggregation + output rendering — the scan gate's single status engine.

One place decides the overall PASS/WARN/BLOCKED/FAIL, mirroring EvalGlass's
"one Verdict Engine" rule. Precedence is BLOCKED > FAIL > WARN > PASS: an
incomplete scan (missing proof / failed tool) is reported as BLOCKED, never
downgraded to a mere FAIL/WARN/PASS, because the gate must be honest about its
own completeness. All findings and the tool ledger are always retained so a
BLOCKED headline never hides the underlying findings.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from scripts.contracts import Finding, ScanResult, Severity, Status, ToolLedgerEntry

# Tool ledger states that mean a required detector could not produce trustworthy
# evidence -> the scan is incomplete -> BLOCKED.
_BLOCKING_ADAPTER_STATES = frozenset({"error", "timeout"})


def aggregate_status(findings: Sequence[Finding], blocked_reasons: Sequence[str]) -> Status:
    severities = {f.severity for f in findings}
    if blocked_reasons or Severity.BLOCK in severities:
        return Status.BLOCKED
    if Severity.FAIL in severities:
        return Status.FAIL
    if Severity.WARN in severities:
        return Status.WARN
    return Status.PASS


def _ledger_blocked_reasons(tool_ledger: Sequence[ToolLedgerEntry]) -> list[str]:
    reasons: list[str] = []
    for entry in tool_ledger:
        if entry.adapter_status in _BLOCKING_ADAPTER_STATES:
            why = entry.skipped_reason or entry.adapter_status
            reasons.append(f"{entry.tool}: {why}")
    return reasons


def build_result(
    *,
    scan_id: str,
    profile_run: str,
    policy_version: str,
    files_scanned: int,
    findings: Sequence[Finding],
    tool_ledger: Sequence[ToolLedgerEntry],
    blocked_reasons: Sequence[str],
    environment: dict[str, str] | None = None,
    coverage_counts: dict[str, int] | None = None,
    coverage_note: str | None = None,
) -> ScanResult:
    findings = list(findings)
    tool_ledger = list(tool_ledger)
    all_blocked = list(blocked_reasons) + _ledger_blocked_reasons(tool_ledger)

    status = aggregate_status(findings, all_blocked)
    summary = {
        "files_scanned": files_scanned,
        "findings": len(findings),
        "failures": sum(1 for f in findings if f.severity is Severity.FAIL),
        "warnings": sum(1 for f in findings if f.severity is Severity.WARN),
        "blocked": sum(1 for f in findings if f.severity is Severity.BLOCK) + len(all_blocked),
    }
    # Coverage counts (machine-readable): so a consumer that reads only the JSON
    # — and suppresses the stderr coverage line — still sees whether the changed
    # code was actually trust-checked or merely swept for secrets.
    if coverage_counts:
        summary.update(coverage_counts)
    environment = dict(environment or {})
    if all_blocked:
        environment["blocked_reasons"] = "; ".join(all_blocked)
    if coverage_note:
        environment["coverage_note"] = coverage_note

    return ScanResult(
        scan_id=scan_id,
        status=status,
        policy_version=policy_version,
        profile_run=profile_run,
        findings=findings,
        tool_ledger=tool_ledger,
        summary=summary,
        environment=environment,
    )


def _md_cell(value: str) -> str:
    """Make a scan-controlled string safe inside a Markdown table cell.

    Findings carry tool stderr / file paths that may contain `|` or newlines;
    unescaped they would forge extra cells/rows. Collapse newlines and escape pipes.
    """
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def render_markdown(result: ScanResult) -> str:
    lines = [
        f"# Scan Gate result: {result.status.value}",
        "",
        f"- profile: `{result.profile_run}`",
        f"- policy: `{result.policy_version}`",
        f"- files scanned: {result.summary.get('files_scanned', 0)}",
        f"- findings: {result.summary.get('findings', 0)} "
        f"(failures {result.summary.get('failures', 0)}, "
        f"warnings {result.summary.get('warnings', 0)}, "
        f"blocked {result.summary.get('blocked', 0)})",
        "",
    ]
    if result.findings:
        lines.append("| severity | rule | location | evidence |")
        lines.append("| --- | --- | --- | --- |")
        for f in result.findings:
            loc = f.file or "-"
            if f.file and f.line is not None:
                loc = f"{f.file}:{f.line}"
            lines.append(
                f"| {_md_cell(f.severity.value)} | `{_md_cell(f.rule_id)}` "
                f"| {_md_cell(loc)} | {_md_cell(f.evidence)} |"
            )
        lines.append("")
    blocked_reasons = result.environment.get("blocked_reasons")
    if blocked_reasons:
        lines.append(f"> BLOCKED — missing proof: {_md_cell(blocked_reasons)}")
        lines.append("")
    lines.append(
        "_Evidence only. The Execution Loop Synthesizer decides the final loop status; "
        "this report does not._"
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    result: ScanResult, json_path: Path | str, markdown_path: Path | str | None
) -> None:
    payload = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(payload, encoding="utf-8")
    if markdown_path is not None:
        markdown_path = Path(markdown_path)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(result), encoding="utf-8")
