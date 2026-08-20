"""Path classifier detector (SG-P1-1).

Routes changed files to policy path groups so other detectors apply the right
rules, and fails closed on ambiguous high-risk paths: a changed file inside the
product source (src/evalglass/) that matches none of the recognized product
groups is treated as an unclassified high-risk path -> BLOCKED, forcing the
policy to keep up with new sensitive locations rather than silently treating a
new core-like module as low risk.
"""

from __future__ import annotations

from scripts.contracts import ToolLedgerEntry
from scripts.detectors.base import DetectorResult, match_groups
from scripts.diffpack import DiffPack
from scripts.policy import Policy

VERSION = "0.1.0"

# Prefix whose files are product source; an unrecognized file here is high-risk.
_PRODUCT_SOURCE_PREFIX = "src/evalglass/"
# Policy group names that count as "recognized" locations within product source.
_PRODUCT_GROUPS = (
    "required_tier",
    "harness",
    "adapters",
    "installer",
    "optional_lane",
    "generated_authority",
)
# A group whose globs are exactly the universal catch-all is excluded from the
# informative per-file classification (it matches everything).
_UNIVERSAL = ("**",)


def _endpoints(f: object) -> list[str]:
    # For renames, both the destination and the source matter: a protected file
    # renamed out of its path must not escape classification via the new path.
    paths = [f.path]  # type: ignore[attr-defined]
    if f.change_type == "renamed" and f.old_path:  # type: ignore[attr-defined]
        paths.append(f.old_path)  # type: ignore[attr-defined]
    return paths


def classify(diff_pack: DiffPack, policy: Policy) -> dict[str, tuple[str, ...]]:
    specific = {name: globs for name, globs in policy.path_groups.items() if globs != _UNIVERSAL}
    table: dict[str, tuple[str, ...]] = {}
    for f in diff_pack.files:
        groups: set[str] = set()
        for p in _endpoints(f):
            groups.update(match_groups(p, specific))
        table[f.path] = tuple(sorted(groups))
    return table


def run(diff_pack: DiffPack, policy: Policy) -> DetectorResult:
    table = classify(diff_pack, policy)
    recognized = tuple(g for g in _PRODUCT_GROUPS if g in policy.path_groups)
    blocked: list[str] = []
    for f in diff_pack.files:
        groups = table[f.path]
        product_endpoints = [p for p in _endpoints(f) if p.startswith(_PRODUCT_SOURCE_PREFIX)]
        if product_endpoints and not any(g in groups for g in recognized):
            offending = ", ".join(repr(p) for p in product_endpoints)
            blocked.append(
                f"path_classifier: ambiguous high-risk path {offending} in product source matches "
                f"no recognized group ({', '.join(recognized)}); update the policy path groups"
            )
    ledger = [
        ToolLedgerEntry(
            tool="path_classifier",
            version=VERSION,
            network="disabled",
            adapter_status="completed",
            findings_count=0,
        )
    ]
    return DetectorResult(findings=[], ledger=ledger, blocked_reasons=blocked)
