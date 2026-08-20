"""Detector orchestration: run a profile's detectors and aggregate results.

Maps each detector name declared by the selected profile to its implementation
and collects findings, tool-ledger entries, and blocked reasons. An
unimplemented detector named by the policy fails closed (BLOCKED) rather than
silently running a partial scan.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from scripts.contracts import Finding, ToolLedgerEntry
from scripts.detectors import (
    ci_script_guard,
    generated_authority,
    imports_effects,
    manifest_drift,
    path_classifier,
    secrets,
)
from scripts.detectors.base import DetectorResult
from scripts.diffpack import DiffPack
from scripts.policy import Policy

_Detector = Callable[[DiffPack, Policy, Path], DetectorResult]

_REGISTRY: dict[str, _Detector] = {
    "path_classifier": lambda dp, pol, root: path_classifier.run(dp, pol),
    "imports_effects": lambda dp, pol, root: imports_effects.run(dp, pol, root),
    "secrets": lambda dp, pol, root: secrets.run(dp, pol, root),
    "generated_authority": lambda dp, pol, root: generated_authority.run(dp, pol, root),
    "ci_script_guard": lambda dp, pol, root: ci_script_guard.run(dp, pol, root),
    "manifest_drift": lambda dp, pol, root: manifest_drift.run(dp, pol, root),
}


def run_detectors(
    diff_pack: DiffPack, policy: Policy, repo_root: Path | str, profile_name: str
) -> tuple[list[Finding], list[ToolLedgerEntry], list[str]]:
    repo_root = Path(repo_root)
    profile = policy.profile(profile_name)
    findings: list[Finding] = []
    ledger: list[ToolLedgerEntry] = []
    blocked: list[str] = []
    for name in profile.detectors:
        detector = _REGISTRY.get(name)
        if detector is None:
            blocked.append(f"runner: no detector implementation for {name!r}")
            continue
        try:
            result = detector(diff_pack, policy, repo_root)
        except Exception as exc:
            blocked.append(f"runner: detector {name!r} crashed: {exc.__class__.__name__}: {exc}")
            ledger.append(
                ToolLedgerEntry(
                    tool=name,
                    version="unknown",
                    network="disabled",
                    adapter_status="error",
                    skipped_reason=exc.__class__.__name__,
                    findings_count=0,
                )
            )
            continue
        findings.extend(result.findings)
        ledger.extend(result.ledger)
        blocked.extend(result.blocked_reasons)
    return findings, ledger, blocked
