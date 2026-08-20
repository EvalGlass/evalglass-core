"""Result composer — the Validator Gate's single status engine (VG-P0-4).

One place turns family findings + evidence problems into a ValidatorResult, the
way EvalGlass has one Verdict Engine. Precedence is FAIL > BLOCKED >
PASS_WITH_WARNINGS > PASS (a proven violation outranks missing proof). A claim
that no family covered cannot be PASS — the gate blocks rather than imply a
proof it does not have. Trust-critical missing proof is BLOCKED, never a
warning. JSON is authoritative; Markdown is a rendering of it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from scripts.contracts import (
    FamilyFinding,
    Status,
    ValidatorResult,
    worst_status,
)


def compose(
    *,
    checkpoint: str,
    claim_ids: Sequence[str],
    findings: Sequence[FamilyFinding],
    families_run: Sequence[str] = (),
    evidence_blocked_on: Sequence[str] = (),
    warnings: Sequence[str] = (),
    evidence_used: Sequence[str] = (),
    risk_references_used: Sequence[str] = (),
) -> ValidatorResult:
    """Aggregate findings + evidence problems into one ValidatorResult."""
    findings = list(findings)
    blocked_on = list(evidence_blocked_on)

    # A claim with no covering finding is unvalidated: the gate must not imply a
    # PASS it did not earn. This also catches a family that was routed but
    # produced no finding for its claim.
    covered = {f.claim_id for f in findings}
    for claim_id in claim_ids:
        if claim_id not in covered:
            blocked_on.append(f"claim {claim_id!r} was not validated by any family")

    statuses = [f.status for f in findings]
    if blocked_on:
        statuses.append(Status.BLOCKED)
    if warnings:
        # A warned run must be distinguishable from a clean pass; FAIL/BLOCKED
        # still outrank PASS_WITH_WARNINGS under the precedence.
        statuses.append(Status.PASS_WITH_WARNINGS)
    status = worst_status(statuses)

    ran = set(families_run) | {f.family_id.value for f in findings}
    used = set(evidence_used)
    for finding in findings:
        used.update(finding.evidence_refs)
    risk_refs = set(risk_references_used) | {f.risk_ref for f in findings if f.risk_ref}

    return ValidatorResult(
        status=status,
        checkpoint=checkpoint,
        families_run=sorted(ran),
        claims_validated=sorted(covered),
        findings=findings,
        evidence_used=sorted(used),
        blocked_on=blocked_on,
        warnings=list(warnings),
        risk_references_used=sorted(r for r in risk_refs if r is not None),
    )


def _md_cell(value: str) -> str:
    """Make a finding-controlled string safe inside a Markdown table cell."""
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def render_markdown(result: ValidatorResult) -> str:
    """Render a Scorecard-style summary. This is a view; the JSON is authoritative."""
    lines = [
        f"# Validator Gate result: {result.status.value}",
        "",
        f"- checkpoint: `{result.checkpoint}`",
        f"- families run: {', '.join(f'`{f}`' for f in result.families_run) or '(none)'}",
        f"- claims validated: {', '.join(f'`{c}`' for c in result.claims_validated) or '(none)'}",
        "",
    ]
    if result.findings:
        lines.append("| family | claim | status | reason | remediation |")
        lines.append("| --- | --- | --- | --- | --- |")
        for f in result.findings:
            lines.append(
                f"| `{_md_cell(f.family_id.value)}` | `{_md_cell(f.claim_id)}` "
                f"| {_md_cell(f.status.value)} | {_md_cell(f.reason)} | {_md_cell(f.remediation)} |"
            )
        lines.append("")
    if result.blocked_on:
        lines.append("> BLOCKED — missing/insufficient proof:")
        for reason in result.blocked_on:
            lines.append(f"> - {_md_cell(reason)}")
        lines.append("")
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"_warning: {_md_cell(warning)}_")
        lines.append("")
    lines.append(
        "_Evidence only. The Execution Loop owns the final decision_record; this result does not._"
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    result: ValidatorResult, json_path: Path | str, markdown_path: Path | str | None = None
) -> None:
    payload = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(payload, encoding="utf-8")
    if markdown_path is not None:
        markdown_path = Path(markdown_path)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(result), encoding="utf-8")
