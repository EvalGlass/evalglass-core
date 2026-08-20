"""EvalGlass Skill — the integration-time installer (M3).

Discovers a host repo, plans an install, vendors the managed runtime under
``evals/_evalglass/``, scaffolds host-owned truth with safe (informational)
defaults, and supports re-vendoring. It runs **only at integration time**: the
vendored runtime (`core`/`harness`/`adapters`) must work after this package and
the coding agent are gone (P13; ADR 0010). Therefore the runtime never imports
``evalglass.installer`` — enforced by ``tests/core_isolation/test_installer_boundary.py``.

The package ``__init__`` deliberately exports only data/functions, never the CLI
orchestrator, to avoid the import-cycle trap (M1 lesson).
"""

from __future__ import annotations

from evalglass.installer.contracts import (
    AuthorityRecord,
    DataPolicyPrompt,
    EvalglassLock,
    HostDiscoveryReport,
    InstallerError,
    InstallPlan,
    ManagedFileRecord,
    VendorManifest,
)
from evalglass.installer.discovery import discover
from evalglass.installer.plan import build_plan
from evalglass.installer.revendor import RevendorPlan, plan_revendor, revendor
from evalglass.installer.scaffold import ScaffoldResult, scaffold
from evalglass.installer.vendor import VendorResult, rewrite_namespace, vendor

__all__ = [
    "AuthorityRecord",
    "DataPolicyPrompt",
    "EvalglassLock",
    "HostDiscoveryReport",
    "InstallPlan",
    "InstallerError",
    "ManagedFileRecord",
    "RevendorPlan",
    "ScaffoldResult",
    "VendorManifest",
    "VendorResult",
    "build_plan",
    "discover",
    "plan_revendor",
    "revendor",
    "rewrite_namespace",
    "scaffold",
    "vendor",
]
