"""Manifest drift detector (SG-P1-5 companion) — WARN only.

Flags changed dependency/manifest files (pyproject.toml, uv.lock, Dockerfiles)
so a reviewer attaches evidence. Lightweight: no SCA/SBOM in the inner loop.
"""

from __future__ import annotations

from pathlib import Path

from scripts.contracts import Finding, Severity, ToolLedgerEntry
from scripts.detectors.base import DetectorResult
from scripts.detectors.path_classifier import classify
from scripts.diffpack import DiffPack
from scripts.policy import Policy

VERSION = "0.1.0"
_CHANGES = {"added", "modified", "renamed", "type_changed", "deleted"}


def run(diff_pack: DiffPack, policy: Policy, _repo_root: Path | str) -> DetectorResult:
    table = classify(diff_pack, policy)
    findings: list[Finding] = []
    for f in diff_pack.files:
        if "manifest" in table[f.path] and f.change_type in _CHANGES:
            findings.append(
                Finding(
                    id=f"SG-MAN-{len(findings) + 1:04d}",
                    rule_id="manifest.review_required",
                    severity=Severity.WARN,
                    surface="manifest",
                    evidence=f"{f.change_type} dependency/manifest file; attach review evidence",
                    tool="manifest_drift",
                    tool_version=VERSION,
                    policy_version=policy.version,
                    recommendation=(
                        "Review the dependency/manifest change and record why it is safe."
                    ),
                    file=f.path,
                    line=None,
                )
            )
    ledger = [
        ToolLedgerEntry(
            tool="manifest_drift",
            version=VERSION,
            network="disabled",
            adapter_status="completed",
            findings_count=len(findings),
        )
    ]
    return DetectorResult(findings=findings, ledger=ledger, blocked_reasons=[])
