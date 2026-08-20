"""Install planning (EG-M3-1).

``build_plan`` turns a read-only :class:`HostDiscoveryReport` into a reviewable
:class:`InstallPlan`. The plan proposes the managed vendoring root and a set of
host-owned scaffolds (provisional, non-authoritative), preserves any existing
host-owned truth untouched, and carries the unanswered data-policy questions
forward. It grants no authority and performs no I/O. Stdlib-only.
"""

from __future__ import annotations

from evalglass.installer.contracts import HostDiscoveryReport, InstallPlan
from evalglass.installer.scaffold import SCAFFOLD_PATHS

MANAGED_ROOT = "evals/_evalglass"

# The proposed host-owned scaffold set is single-sourced from ``scaffold.SCAFFOLD_PATHS``,
# so the reviewable plan can never drift from what ``install`` actually writes. These are
# *proposed* starter assets — informational by construction (see scaffold/safe defaults).
_DEFAULT_SCAFFOLDS = SCAFFOLD_PATHS


def build_plan(report: HostDiscoveryReport, *, managed_root: str = MANAGED_ROOT) -> InstallPlan:
    """Build a reviewable, non-authoritative install plan from a discovery report."""
    blockers: list[str] = []
    if report.language != "python":
        blockers.append(
            f"Host language {report.language!r} is not supported by the M3 skill "
            "(Python hosts only); integration cannot proceed without host guidance."
        )

    # Existing host-owned truth is preserved, never re-proposed or overwritten.
    preserved = list(report.eval_assets)
    preserved_set = set(preserved)
    proposed = [path for path in _DEFAULT_SCAFFOLDS if path not in preserved_set]

    return InstallPlan(
        root=report.root,
        managed_root=managed_root,
        proposed_host_assets=proposed,
        preserved_paths=preserved,
        questions=list(report.data_policy_prompts),
        blockers=blockers,
    )
