"""Generated-authority / host-owned guard (SG-P1-4).

Enforces two trust-model rules on the diff:
  * generated authority (baselines / calibration / thresholds) that is added or
    modified must carry an explicit approval marker, else FAIL -- generated data
    is informational until validated;
  * host-owned files (datasets / rubrics / evaluators) must not be overwritten or
    deleted by scaffolding/vendoring (adding a new one is fine), else FAIL.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.contracts import Finding, Severity, ToolLedgerEntry
from scripts.detectors.base import DetectorResult, path_matches
from scripts.detectors.path_classifier import classify
from scripts.diffpack import DiffPack
from scripts.policy import Policy

VERSION = "0.1.0"

# An explicit, reviewable approval marker inside the generated-authority file.
_APPROVAL_MARKER = re.compile(
    r'(?i)(evalglass[\s:_-]*approved|"approved_by"|"approval_record"|approved[\s_-]*by\s*:)'
)

# Adding/modifying generated authority needs approval; a type change clobbers it too.
_GENERATED_CHANGES = {"added", "modified", "renamed", "type_changed"}
# Modifying/deleting/type-changing an existing host-owned file is an overwrite
# (renames are handled separately, by checking the *source* endpoint).
_OVERWRITE_CHANGES = {"modified", "deleted", "type_changed"}


def _has_approval(path: Path) -> bool:
    # A symlink cannot carry an inline approval marker; never follow it to a
    # target that might contain "approved_by" outside the diff.
    if path.is_symlink():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _APPROVAL_MARKER.search(text) is not None


def _in_group(path: str, policy: Policy, group: str) -> bool:
    return any(path_matches(path, g) for g in policy.path_groups.get(group, ()))


def run(diff_pack: DiffPack, policy: Policy, repo_root: Path | str) -> DetectorResult:
    repo_root = Path(repo_root)
    table = classify(diff_pack, policy)
    findings: list[Finding] = []

    def add(rule_id: str, surface: str, evidence: str, file: str, recommendation: str) -> None:
        findings.append(
            Finding(
                id=f"SG-GEN-{len(findings) + 1:04d}",
                rule_id=rule_id,
                severity=Severity.FAIL,
                surface=surface,
                evidence=evidence,
                tool="generated_authority",
                tool_version=VERSION,
                policy_version=policy.version,
                recommendation=recommendation,
                file=file,
                line=None,
            )
        )

    for f in diff_pack.files:
        groups = table[f.path]
        if (
            "generated_authority" in groups
            and f.change_type in _GENERATED_CHANGES
            and not _has_approval(repo_root / f.path)
        ):
            add(
                "generated.no_unmarked_authority",
                "generated_authority",
                f"{f.change_type} generated-authority file without an approval marker",
                f.path,
                "Have a domain owner validate it and add an approval marker, or keep it "
                "informational.",
            )
        if "host_owned" in groups:
            # A rename only clobbers host truth if the *source* was host-owned;
            # renaming a non-host file into the group is an allowed add.
            is_overwrite = f.change_type in _OVERWRITE_CHANGES or (
                f.change_type == "renamed"
                and f.old_path is not None
                and _in_group(f.old_path, policy, "host_owned")
            )
            if is_overwrite:
                add(
                    "generated.no_host_owned_overwrite",
                    "host_owned",
                    f"{f.change_type} host-owned file "
                    "(scaffolding/vendoring must not clobber host truth)",
                    f.path,
                    "Do not overwrite or delete host-owned files; only the host may change them.",
                )

    ledger = [
        ToolLedgerEntry(
            tool="generated_authority",
            version=VERSION,
            network="disabled",
            adapter_status="completed",
            findings_count=len(findings),
        )
    ]
    return DetectorResult(findings=findings, ledger=ledger, blocked_reasons=[])
