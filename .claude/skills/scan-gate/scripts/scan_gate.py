#!/usr/bin/env python3
"""scan-gate CLI — the single behavior source for the skill.

Slice 2 ships the `diff` subcommand: build the deterministic git diff pack and
emit it as JSON. Later slices add `run` (policy + detectors + scan-gate.result.json).

Exit codes: 0 = ok; 2 = BLOCKED (missing proof: bad ref, non-git repo) or usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running directly (`python .../scripts/scan_gate.py`) as well as being
# imported as `scripts.scan_gate`: ensure the skill root is importable.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from scripts.contracts import ScanResult, Status  # noqa: E402
from scripts.coverage import (  # noqa: E402
    build_coverage,
    coverage_counts,
    coverage_note,
    render_debug,
    summary_line,
)
from scripts.diffpack import DiffError, build_diff_pack  # noqa: E402
from scripts.policy import PolicyError, load_policy  # noqa: E402
from scripts.result_builder import build_result, write_outputs  # noqa: E402
from scripts.runner import run_detectors  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        pack = build_diff_pack(
            args.repo,
            args.base,
            args.head,
            include_untracked=args.include_untracked,
        )
    except DiffError as exc:
        blocked = {"status": "BLOCKED", "reason": str(exc)}
        print(json.dumps(blocked), file=sys.stderr)
        return EXIT_BLOCKED

    payload = json.dumps(pack.to_dict(), indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)
    return EXIT_OK


def _cmd_policy(args: argparse.Namespace) -> int:
    try:
        policy = load_policy(args.policy)
        if args.profile is not None:
            policy.profile(args.profile)  # raises PolicyError if unknown
    except PolicyError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return EXIT_BLOCKED
    summary = {
        "status": "OK",
        "version": policy.version,
        "profiles": sorted(policy.profiles),
        "path_groups": sorted(policy.path_groups),
        "rules": len(policy.rules),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return EXIT_OK


def _emit_and_exit(result: ScanResult, args: argparse.Namespace) -> int:
    if args.json:
        write_outputs(result, args.json, args.markdown)
    print(
        json.dumps(
            {"status": result.status.value, "summary": result.summary}, indent=2, sort_keys=True
        )
    )
    if result.status in (Status.PASS, Status.WARN):
        return EXIT_OK
    return EXIT_FAIL if result.status is Status.FAIL else EXIT_BLOCKED


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        policy = load_policy(args.policy)
        policy.profile(args.profile)
    except PolicyError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return EXIT_BLOCKED

    scan_id = args.scan_id or f"scan.{args.profile}"
    try:
        diff_pack = build_diff_pack(
            args.repo, args.base, args.head, include_untracked=args.include_untracked
        )
    except DiffError as exc:
        blocked_result = build_result(
            scan_id=scan_id,
            profile_run=args.profile,
            policy_version=policy.version,
            files_scanned=0,
            findings=[],
            tool_ledger=[],
            blocked_reasons=[f"diff: {exc}"],
            environment={"network": policy.profile(args.profile).network},
        )
        return _emit_and_exit(blocked_result, args)

    # Coverage report (stderr only): make it visible whether the changed files
    # were actually inspected by a path-scoped trust detector, or merely fell
    # through to the universal sweep. A bare PASS over out-of-scope changes must
    # not be mistaken for a clean trust check.
    coverage = build_coverage(diff_pack, policy, args.profile)
    if getattr(args, "debug", False):
        print(render_debug(coverage), file=sys.stderr)
    else:
        note = summary_line(coverage)
        if note is not None:
            print(note, file=sys.stderr)

    findings, ledger, blocked = run_detectors(diff_pack, policy, args.repo, args.profile)
    result = build_result(
        scan_id=scan_id,
        profile_run=args.profile,
        policy_version=policy.version,
        files_scanned=len(diff_pack.files),
        findings=findings,
        tool_ledger=ledger,
        blocked_reasons=blocked,
        environment={"network": policy.profile(args.profile).network},
        coverage_counts=coverage_counts(coverage),
        coverage_note=coverage_note(coverage),
    )
    return _emit_and_exit(result, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scan-gate", description="EvalGlass diff-aware policy scanner."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    diff = sub.add_parser("diff", help="Build and emit the git diff pack as JSON.")
    diff.add_argument("--repo", required=True, help="Repository root.")
    diff.add_argument("--base", required=True, help="Base ref to diff against.")
    diff.add_argument(
        "--head", default="HEAD", help="Head committish, or WORKTREE for the working tree."
    )
    diff.add_argument(
        "--include-untracked",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include untracked files (working-tree head only).",
    )
    diff.add_argument("--out", default=None, help="Write JSON here instead of stdout.")
    diff.set_defaults(func=_cmd_diff)

    policy = sub.add_parser(
        "policy", help="Validate a policy file and optionally resolve a profile."
    )
    policy.add_argument("--policy", required=True, help="Path to a policy YAML file.")
    policy.add_argument("--profile", default=None, help="Profile to resolve (validates it exists).")
    policy.set_defaults(func=_cmd_policy)

    run = sub.add_parser("run", help="Scan a diff and emit scan-gate.result.json.")
    run.add_argument("--repo", required=True, help="Repository root.")
    run.add_argument("--base", required=True, help="Base ref to diff against.")
    run.add_argument(
        "--head", default="HEAD", help="Head committish, or WORKTREE for the working tree."
    )
    run.add_argument(
        "--profile", required=True, help="Policy profile to run (e.g. fast, required)."
    )
    run.add_argument("--policy", required=True, help="Path to a policy YAML file.")
    run.add_argument("--scan-id", default=None, help="Optional scan id.")
    run.add_argument(
        "--include-untracked",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include untracked files (working-tree head only).",
    )
    run.add_argument("--json", default=None, help="Write scan-gate.result.json here.")
    run.add_argument("--markdown", default=None, help="Write the Markdown summary here.")
    run.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Print a per-file detector-coverage table to stderr "
            "(which detectors inspected each changed file)."
        ),
    )
    run.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
