"""The ``egts`` command surface (EGTS-M0-2 foundation).

A thin CLI over the EGTS proof system. M0 ships ``egts coverage``; the milestone
proof commands (``test-core`` etc.) attach as their suites land. The CLI reports;
it never computes a product verdict or grants authority (``tests/CLAUDE.md §3``).

Invocation. EGTS is repo test tooling, not part of the vendored product wheel, so
there is no installed ``egts`` console script. The runnable, documented-equivalent
form (``test_architecture_build_contract.md §14``) is::

    python -m tests.egts.cli coverage --registry tests/egts/coverage/eg_m0.yaml

``egts <command>`` is the logical command-surface name used in docs and coverage
rows; a console-script alias can be added when EGTS gets a packaging entry.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from tests.egts.coverage_registry import (
    CoverageStatus,
    find_gaps,
    integrity_violations,
    load_registry,
)

_EGTS_DIR = Path(__file__).resolve().parents[1]


def _cmd_coverage(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)

    counts: dict[str, int] = {status.value: 0 for status in CoverageStatus}
    for row in registry.rows:
        counts[row.status.value] += 1

    gaps = find_gaps(registry)
    violations = integrity_violations(registry)

    print(f"coverage: {len(registry.rows)} obligation(s)")
    for status_value, count in counts.items():
        if count:
            print(f"  {status_value}: {count}")

    deferred = [row for row in registry.rows if row.is_not_exercised]
    if deferred:
        print(f"\ndeferred / not exercised ({len(deferred)}):")
        for row in deferred:
            print(
                f"  NOT EXERCISED — {row.not_exercised_reason} "
                f"({row.product_ticket} :: {row.public_contract})"
            )

    if gaps:
        print(f"\nopen / unproven obligations ({len(gaps)}):")
        for row in gaps:
            tag = "OVERCLAIM" if row.is_integrity_violation else row.status.value
            print(f"  [{tag}] {row.product_ticket} :: {row.public_contract}")

    # Integrity violations (covered-with-no-scenario) always fail: that is a lie.
    if violations:
        print(f"\nFAIL: {len(violations)} integrity violation(s) — 'covered' with no scenario.")
        return 1
    # Open gaps fail only under --require-complete (used at milestone acceptance).
    if args.require_complete and gaps:
        print(f"\nFAIL: {len(gaps)} obligation(s) not covered (--require-complete).")
        return 1
    return 0


def _cmd_evidence(args: argparse.Namespace) -> int:
    """Report a reviewable evidence summary for a target from the coverage registry."""
    registry = load_registry(args.registry)
    gaps = find_gaps(registry)
    violations = integrity_violations(registry)
    print(f"evidence target: {args.target}")
    print(
        f"  obligations={len(registry.rows)} gaps={len(gaps)} "
        f"integrity_violations={len(violations)}"
    )
    for row in registry.rows:
        scenarios = ", ".join(row.scenario_ids) or "(none)"
        print(f"  [{row.status.value}] {row.product_ticket} :: {scenarios}")
    return 1 if (gaps or violations) else 0


def _cmd_test_core(args: argparse.Namespace) -> int:
    """Run the EGTS-M0 proof suite (documented equivalent: ``pytest tests/egts``).

    Pass extra pytest flags after ``--``, e.g. ``egts test-core -- -k blocked``.
    """
    return _pytest([_EGTS_DIR], args.pytest_args)


#: The EGTS-M1 runtime proof: workspace isolation + dataset/trace/mixed routes + artifacts +
#: the shipped quickstart (its EG-M1-6 coverage row names ``egts test-runtime``).
_M1_RUNTIME_TARGETS = (
    _EGTS_DIR / "test_workspace.py",
    _EGTS_DIR / "suites" / "test_m1_runtime_proof.py",
    _EGTS_DIR / "suites" / "test_m1_artifact_proof.py",
    _EGTS_DIR / "suites" / "test_m1_acceptance.py",
    _EGTS_DIR.parent / "examples" / "test_quickstart.py",
)


def _cmd_test_runtime(args: argparse.Namespace) -> int:
    """Run the EGTS-M1 local runtime route + artifact proof."""
    return _pytest(list(_M1_RUNTIME_TARGETS), args.pytest_args)


#: The EGTS-M2 trust-runtime proof: subprocess TaskRunner route, baseline comparability,
#: data-policy egress, CI exit/annotation, infra-error taxonomy + the deterministic
#: replay/baseline acceptance scenarios driven through the real CLI.
_M2_TRUST_TARGETS = (
    _EGTS_DIR / "suites" / "test_m2_trust_runtime_proof.py",
    _EGTS_DIR / "suites" / "test_m2_baseline_policy_proof.py",
    _EGTS_DIR / "suites" / "test_m2_ci_taxonomy_proof.py",
    _EGTS_DIR / "suites" / "test_m2_acceptance.py",
    # Product trust scenarios named by the EG-M2 coverage rows (explicit-promotion-only and the
    # trace per-record egress override) must run under the required command too.
    _EGTS_DIR.parent / "harness" / "test_m2_acceptance.py",
    _EGTS_DIR.parent / "harness" / "test_baseline_promote.py",
    _EGTS_DIR.parent / "harness" / "test_data_policy.py",
)


def _cmd_test_trust_runtime(args: argparse.Namespace) -> int:
    """Run the EGTS-M2 trust-runtime proof (replay, baselines, data policy, CI exits)."""
    return _pytest(list(_M2_TRUST_TARGETS), args.pytest_args)


#: The EGTS-M3 skill proof: discovery/plan read-only, vendoring boundary + manifest/lock,
#: safe scaffold (no silent authority), runtime independence, and safe re-vendor — driven
#: through the real ``evalglass.installer`` surfaces and the vendored runtime. Includes the
#: product-layer skill trust tests the coverage rows name (not only the EGTS suite) and the
#: runtime import-boundary guard.
_M3_SKILL_TARGETS = (
    _EGTS_DIR / "suites" / "test_m3_skill_proof.py",
    _EGTS_DIR / "suites" / "test_m3_acceptance.py",
    _EGTS_DIR.parent / "skill",
    _EGTS_DIR.parent / "core_isolation" / "test_installer_boundary.py",
)


def _cmd_test_skill(args: argparse.Namespace) -> int:
    """Run the EGTS-M3 skill + vendoring proof (discovery, manifest, scaffold, independence)."""
    return _pytest(list(_M3_SKILL_TARGETS), args.pytest_args)


#: The EGTS-M4 judge proof: fake-judge route, rubric provenance, calibration/threshold/drift
#: authority, judge scorecard/report — driven through the real harness, plus the product-layer
#: judge trust tests the EG-M4 coverage rows name and the optional-lane deletion guard.
_M4_JUDGE_TARGETS = (
    _EGTS_DIR / "suites" / "test_m4_judge_proof.py",
    _EGTS_DIR / "suites" / "test_m4_acceptance.py",
    _EGTS_DIR.parent / "core" / "test_judge_evidence.py",
    _EGTS_DIR.parent / "core" / "test_judge_score.py",
    _EGTS_DIR.parent / "adapters" / "test_judge_fake.py",
    _EGTS_DIR.parent / "adapters" / "test_judge_live.py",
    _EGTS_DIR.parent / "harness" / "test_judge.py",
    _EGTS_DIR.parent / "harness" / "test_rubric.py",
    _EGTS_DIR.parent / "harness" / "test_calibration.py",
    _EGTS_DIR.parent / "core_isolation" / "test_judge_live_boundary.py",
)


def _cmd_test_judges(args: argparse.Namespace) -> int:
    """Run the EGTS-M4 fake-judge, rubric, calibration, and judge-score proof."""
    return _pytest(list(_M4_JUDGE_TARGETS), args.pytest_args)


#: EGTS-M5 optional-lane proofs, keyed by the ``egts test-lane <name>`` token. Each lane's proof
#: is its own target set; lanes are NEVER part of a required milestone suite (test-core/runtime/
#: trust-runtime/skill/judges) — they run only on demand here. Lanes attach as the M5a slices land.
_LANE_TARGETS: dict[str, tuple[Path, ...]] = {
    "lane-framework": (
        _EGTS_DIR / "suites" / "test_m5a_lane_framework_proof.py",
        _EGTS_DIR.parent / "harness" / "test_lanes.py",
        _EGTS_DIR.parent / "core_isolation" / "test_lane_boundary.py",
    ),
    "open-convention-traces": (
        _EGTS_DIR / "suites" / "test_m5a_conformance_lane_proof.py",
        _EGTS_DIR.parent / "adapters" / "test_trace_open_convention.py",
    ),
    "trace-backend": (
        _EGTS_DIR / "suites" / "test_m5a_trace_backend_proof.py",
        _EGTS_DIR.parent / "adapters" / "test_trace_backend_stub.py",
    ),
    "score-sink": (
        _EGTS_DIR / "suites" / "test_m5a_score_sink_proof.py",
        _EGTS_DIR.parent / "adapters" / "test_score_sink_export.py",
    ),
    "richer-units": (
        _EGTS_DIR / "suites" / "test_m5b_richer_units_proof.py",
        _EGTS_DIR.parent / "adapters" / "test_async_observation.py",
        _EGTS_DIR.parent / "core" / "test_richer_units.py",
        _EGTS_DIR.parent / "core" / "test_trajectory_shape.py",
        _EGTS_DIR.parent / "harness" / "test_units.py",
    ),
    "evidence-workflows": (
        _EGTS_DIR / "suites" / "test_m5b_governance_proof.py",
        _EGTS_DIR.parent / "harness" / "test_governance.py",
    ),
}


def _cmd_test_lane(args: argparse.Namespace) -> int:
    """Run one optional lane's proof (``egts test-lane <name>``); not part of any required suite."""
    name = args.lane
    if name not in _LANE_TARGETS:
        known = ", ".join(sorted(_LANE_TARGETS)) or "(none registered yet)"
        print(f"unknown lane {name!r}; known lanes: {known}")
        return 2
    return _pytest(list(_LANE_TARGETS[name]), args.pytest_args)


def _cmd_verify_deletion(args: argparse.Namespace) -> int:
    """Prove every optional lane is removable: required tier imports no lane, survives deletion."""
    from evalglass.harness.lanes import built_in_lanes

    lanes = built_in_lanes().lanes()
    print(f"verify-deletion: {len(lanes)} optional lane(s) — proving each is removable")
    for lane in lanes:
        print(f"  - {lane.name} ({lane.module}): {lane.deletion_rule}")
    targets = [
        _EGTS_DIR / "suites" / "test_m5a_deletion_proof.py",
        _EGTS_DIR / "suites" / "test_m5b_acceptance.py",
    ]
    return _pytest(targets, args.pytest_args)


def _cmd_verify_managed_boundary(args: argparse.Namespace) -> int:
    """Verify the managed/host-owned vendoring boundary (EGTS-M3-2) via the boundary proofs."""
    targets = [
        _EGTS_DIR / "suites" / "test_m3_skill_proof.py",
        _EGTS_DIR.parent / "core_isolation" / "test_installer_boundary.py",
    ]
    return _pytest(targets, ["-k", "boundary or managed or manifest or preserve or independence"])


def _pytest(targets: Sequence[Path], extra: Sequence[str]) -> int:
    cleaned = list(extra)
    if cleaned and cleaned[0] == "--":  # argparse.REMAINDER keeps the separator
        cleaned = cleaned[1:]
    cmd = [sys.executable, "-m", "pytest", *(str(t) for t in targets), "-q", *cleaned]
    return subprocess.run(cmd, check=False).returncode  # noqa: S603 — fixed interpreter + pytest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="egts", description="EvalGlass Testing System.")
    sub = parser.add_subparsers(dest="command", required=True)

    coverage = sub.add_parser(
        "coverage", help="Report coverage completeness and missing obligations."
    )
    coverage.add_argument(
        "--registry", required=True, help="Path to a coverage registry YAML file."
    )
    coverage.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero if any obligation is an open gap (milestone-acceptance mode).",
    )
    coverage.set_defaults(func=_cmd_coverage)

    evidence = sub.add_parser("evidence", help="Emit a reviewable evidence summary for a target.")
    evidence.add_argument(
        "--registry", required=True, help="Path to a coverage registry YAML file."
    )
    evidence.add_argument("--target", required=True, help="Proof target, e.g. EGTS-M0.")
    evidence.set_defaults(func=_cmd_evidence)

    test_core = sub.add_parser("test-core", help="Run the EGTS-M0 core proof suite.")
    test_core.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    test_core.set_defaults(func=_cmd_test_core)

    test_runtime = sub.add_parser("test-runtime", help="Run the EGTS-M1 runtime route proof.")
    test_runtime.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    test_runtime.set_defaults(func=_cmd_test_runtime)

    test_trust = sub.add_parser(
        "test-trust-runtime", help="Run the EGTS-M2 trust-runtime proof (replay, baselines, CI)."
    )
    test_trust.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    test_trust.set_defaults(func=_cmd_test_trust_runtime)

    test_skill = sub.add_parser(
        "test-skill",
        help="Run the EGTS-M3 skill + vendoring proof (discovery, manifest, scaffold).",
    )
    test_skill.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    test_skill.set_defaults(func=_cmd_test_skill)

    test_judges = sub.add_parser(
        "test-judges",
        help="Run the EGTS-M4 judge proof (fake judge, rubric, calibration, judge_score).",
    )
    test_judges.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    test_judges.set_defaults(func=_cmd_test_judges)

    verify_boundary = sub.add_parser(
        "verify-managed-boundary",
        help="Verify the managed vs host-owned vendoring boundary (EGTS-M3-2).",
    )
    verify_boundary.set_defaults(func=_cmd_verify_managed_boundary)

    test_lane = sub.add_parser(
        "test-lane",
        help="Run one optional extension lane's proof (EGTS-M5); never part of a required suite.",
    )
    test_lane.add_argument("lane", help="Lane name, e.g. lane-framework, open-convention-traces.")
    test_lane.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    test_lane.set_defaults(func=_cmd_test_lane)

    verify_deletion = sub.add_parser(
        "verify-deletion",
        help="Prove every optional lane is removable (EGTS-M5-7): required tier survives it.",
    )
    verify_deletion.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed through to pytest (e.g. -k pattern, --maxfail=1).",
    )
    verify_deletion.set_defaults(func=_cmd_verify_deletion)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: object = args.func
    assert callable(func)
    return int(func(args))
