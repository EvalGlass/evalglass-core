"""Diff coverage report — which policy rules actually inspected each changed file.

Answers the question a bare ``PASS`` cannot: *was the changed code actually
trust-checked, or did it simply fall outside every path-scoped rule?*

A scan over files that match only the universal ``all`` group runs the
secrets sweep and nothing else: none of the path-scoped trust detectors
(core effects, verdict duplication, generated-authority, host-owned overwrite,
CI/script spoof) ever look at them. The result is a legitimate ``PASS`` with
zero findings — which, reported as a bare status, is indistinguishable from
"8 files were trust-checked and are clean". This module makes that distinction
visible so a green scan over out-of-scope changes is never silently misread as
a clean trust check.

Coverage is derived from the policy itself (rules' ``applies_to`` groups for the
active profile's detectors), so it stays correct as the policy evolves. Output
goes to stderr; it never alters the authoritative ``scan-gate.result.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.detectors.base import match_groups
from scripts.diffpack import DiffPack
from scripts.policy import Policy


def _universal_groups(policy: Policy) -> frozenset[str]:
    """Group names whose globs are exactly the catch-all ``**`` (match everything)."""
    return frozenset(name for name, globs in policy.path_groups.items() if tuple(globs) == ("**",))


@dataclass(frozen=True)
class FileCoverage:
    path: str
    groups: tuple[str, ...]  # every path group this file matched
    detectors: tuple[str, ...]  # active detectors that actually inspect this file
    rules: tuple[str, ...]  # rule ids whose applies_to intersects this file's groups
    trust_scoped: bool  # True iff a matched rule applies via a non-universal group


@dataclass(frozen=True)
class CoverageReport:
    profile: str
    files: tuple[FileCoverage, ...]

    @property
    def universal_only(self) -> tuple[FileCoverage, ...]:
        """Files inspected only via universal group(s) — no path-scoped trust detector ran."""
        return tuple(f for f in self.files if not f.trust_scoped)

    @property
    def has_blind_spot(self) -> bool:
        return bool(self.files) and bool(self.universal_only)


def build_coverage(diff_pack: DiffPack, policy: Policy, profile_name: str) -> CoverageReport:
    profile = policy.profile(profile_name)
    active = set(profile.detectors)
    universal = _universal_groups(policy)
    groups_map = {name: tuple(globs) for name, globs in policy.path_groups.items()}

    files: list[FileCoverage] = []
    for f in diff_pack.files:
        matched = set(match_groups(f.path, groups_map))
        applicable = [
            r for r in policy.rules if r.detector in active and (set(r.applies_to) & matched)
        ]
        detectors = tuple(sorted({r.detector for r in applicable}))
        rule_ids = tuple(sorted({r.id for r in applicable}))
        # "trust-scoped" = inspected because it matched a group narrower than the
        # universal catch-all (i.e. a real product/trust surface), not merely 'all'.
        trust_scoped = any((set(r.applies_to) - universal) & matched for r in applicable)
        files.append(
            FileCoverage(
                path=f.path,
                groups=tuple(sorted(matched)),
                detectors=detectors,
                rules=rule_ids,
                trust_scoped=trust_scoped,
            )
        )
    return CoverageReport(profile=profile_name, files=tuple(files))


def summary_line(report: CoverageReport) -> str | None:
    """One honest line for stderr, or None when every changed file is trust-scoped."""
    if not report.has_blind_spot:
        return None
    n, total = len(report.universal_only), len(report.files)
    return (
        f"scan-gate: coverage — {n}/{total} changed file(s) matched only the universal group; "
        f"no path-scoped trust detector inspected them. A PASS here is NOT a trust check of "
        f"that code (use --debug for the per-file table)."
    )


def coverage_counts(report: CoverageReport) -> dict[str, int]:
    """Integer coverage counts for the ScanResult summary (machine-readable).

    Consumers that read scan-gate.result.json (and suppress stderr) still see
    whether the scan actually trust-checked the changed code.
    """
    trust_scoped = sum(1 for f in report.files if f.trust_scoped)
    return {"trust_scoped": trust_scoped, "not_trust_scoped": len(report.files) - trust_scoped}


def coverage_note(report: CoverageReport) -> str | None:
    """A JSON-friendly note (names the untrusted files) when a blind spot exists."""
    if not report.has_blind_spot:
        return None
    untrusted = [f.path for f in report.universal_only]
    n, total = len(untrusted), len(report.files)
    listed = ", ".join(untrusted[:8]) + (" …" if n > 8 else "")
    return (
        f"{n}/{total} changed file(s) matched only the universal group and were NOT trust-checked "
        f"by any path-scoped detector; a PASS does not vouch for them: {listed}"
    )


def render_debug(report: CoverageReport) -> str:
    lines = [f"scan-gate: detector coverage (profile={report.profile})", ""]
    width = max((len(f.path) for f in report.files), default=4)
    lines.append(f"  {'FILE'.ljust(width)}  TRUST?  DETECTORS")
    for f in report.files:
        flag = "yes" if f.trust_scoped else "NO "
        detectors = ", ".join(f.detectors) if f.detectors else "(none)"
        lines.append(f"  {f.path.ljust(width)}  {flag}     {detectors}  groups={list(f.groups)}")
    note = summary_line(report)
    if note:
        lines += ["", "  " + note]
    return "\n".join(lines)
