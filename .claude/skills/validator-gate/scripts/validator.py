#!/usr/bin/env python3
"""validator-gate CLI — the single behavior source for the skill.

Subcommands:
- `run`: read an evidence pack, build the claim/artifact index, compose a
  ValidatorResult, and emit validator.result.json (+ optional Markdown).
- `validate-evidence`: report whether an evidence pack is structurally usable
  (source boundary + required artifacts), without running families.

Routing and the five semantic families land in later slices; until then `run`
honestly blocks a clean pack (its claims are not yet validated by any family)
rather than imply a PASS. Exit codes: PASS / PASS_WITH_WARNINGS -> 0,
FAIL -> 1, BLOCKED -> 2; an unreadable pack or usage error -> 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running directly as well as `import scripts.validator`: put skill root on path.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from scripts.adapter import materialize_adjacent, run_adapter  # noqa: E402
from scripts.composer import render_markdown, write_outputs  # noqa: E402
from scripts.contracts import Status, ValidatorResult  # noqa: E402
from scripts.evidence import EvidenceError, load_pack  # noqa: E402
from scripts.index import EvidenceIndex  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2


def _exit_code(result: ValidatorResult) -> int:
    if result.status in (Status.PASS, Status.PASS_WITH_WARNINGS):
        return EXIT_OK
    return EXIT_FAIL if result.status is Status.FAIL else EXIT_BLOCKED


def _emit(result: ValidatorResult, args: argparse.Namespace) -> int:
    if args.json:
        write_outputs(result, args.json, args.markdown)
    elif args.markdown:
        # --markdown without --json must still write the requested file, not no-op.
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {"status": result.status.value, "blocked_on": result.blocked_on},
            indent=2,
            sort_keys=True,
        )
    )
    return _exit_code(result)


def _cmd_run(args: argparse.Namespace) -> int:
    # The adapter loads the pack, materializes adjacent-gate evidence, and runs
    # the core. _emit writes the JSON/Markdown and maps the status to an exit code.
    # --debug writes a non-authoritative trace to stderr (never affects status/JSON).
    trace_sink = sys.stderr if args.debug else None
    result, _ = run_adapter(args.evidence_pack, checkpoint=args.checkpoint, trace_sink=trace_sink)
    return _emit(result, args)


def _cmd_validate_evidence(args: argparse.Namespace) -> int:
    try:
        pack = load_pack(args.evidence_pack)
    except EvidenceError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2))
        return EXIT_BLOCKED
    # Materialize adjacent-gate evidence so the preflight matches `run`.
    pack = materialize_adjacent(pack)
    index = EvidenceIndex.build(pack)
    summary = {
        "status": "OK" if index.ok else "BLOCKED",
        "checkpoint": pack.checkpoint,
        "claims": len(pack.claims),
        "artifacts": len(pack.artifacts),
        "blocked_on": index.blocked_on,
        "warnings": index.warnings,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return EXIT_OK if index.ok else EXIT_BLOCKED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validator", description="EvalGlass Validator Gate.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Validate an evidence pack and emit validator.result.json.")
    run.add_argument("--evidence-pack", required=True, help="Path to an evidence-pack JSON file.")
    run.add_argument("--checkpoint", default=None, help="Override the checkpoint label.")
    run.add_argument("--json", default=None, help="Write validator.result.json here.")
    run.add_argument("--markdown", default=None, help="Write the Markdown summary here.")
    run.add_argument(
        "--debug",
        action="store_true",
        help="Write a non-authoritative routing/coverage/evidence trace to stderr.",
    )
    run.set_defaults(func=_cmd_run)

    ve = sub.add_parser("validate-evidence", help="Check an evidence pack is structurally usable.")
    ve.add_argument("--evidence-pack", required=True, help="Path to an evidence-pack JSON file.")
    ve.set_defaults(func=_cmd_validate_evidence)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
