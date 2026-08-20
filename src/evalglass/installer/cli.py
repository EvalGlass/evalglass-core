"""The ``evalglass-install`` command-line entrypoint (EG-M3-1).

A thin argparse wrapper over the integration-time skill engine. ``discover`` and
``plan`` are **read-only** (inspect + print a typed JSON artifact); ``install``
vendors the managed runtime under ``evals/_evalglass/`` and scaffolds host-owned
assets; ``revendor`` safely re-vendors/upgrades (``--dry-run`` to preview,
``--confirm`` to overwrite a host-patched managed file). The CLI owns no authority.
Stdlib-only; never imported by the runtime (`core`/`harness`/`adapters`) —
integration-time only (ADR 0010).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalglass-install",
        description="EvalGlass integration-time skill (discover / plan / install / revendor).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser(
        "discover", help="Inspect a host repo (read-only) and print a report."
    )
    discover.add_argument("--root", required=True, help="Path to the host repository root.")

    plan = sub.add_parser("plan", help="Print the proposed (non-authoritative) install plan.")
    plan.add_argument("--root", required=True, help="Path to the host repository root.")

    install = sub.add_parser("install", help="Vendor the managed runtime into the host repo.")
    install.add_argument("--root", required=True, help="Path to the host repository root.")

    rev = sub.add_parser("revendor", help="Safely re-vendor / upgrade the managed runtime.")
    rev.add_argument("--root", required=True, help="Path to the host repository root.")
    rev.add_argument(
        "--dry-run", action="store_true", help="Show what would change; write nothing."
    )
    rev.add_argument(
        "--confirm",
        action="store_true",
        help="Proceed even if it would overwrite a host-patched managed file (the patch is lost).",
    )
    return parser


def _emit(payload: dict[str, object]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _discover(root: str) -> int:
    from evalglass.installer.discovery import discover

    return _emit(discover(Path(root)).to_dict())


def _plan(root: str) -> int:
    from evalglass.installer.discovery import discover
    from evalglass.installer.plan import build_plan

    return _emit(build_plan(discover(Path(root))).to_dict())


def _install(root: str) -> int:
    import evalglass
    from evalglass.installer.scaffold import scaffold
    from evalglass.installer.vendor import vendor

    host = Path(root)
    framework_pkg = Path(evalglass.__file__).resolve().parent
    vendored = vendor(framework_pkg, host, framework_version=evalglass.__version__)
    # Scaffold host-owned starter assets with safe (informational) defaults — never overwriting
    # existing host truth. Authority stays empty: a fresh install's first run is informational.
    scaffolded = scaffold(host)
    return _emit(
        {
            "vendored_files": len(vendored.written),
            "managed_root": vendored.manifest.managed_root,
            "framework_version": vendored.lock.framework_version,
            "installed_features": vendored.lock.installed_features,
            "scaffolded": scaffolded.created,
            "preserved": scaffolded.preserved,
        }
    )


def _revendor(root: str, *, dry_run: bool, confirm: bool) -> int:
    import evalglass
    from evalglass.installer.contracts import InstallerError
    from evalglass.installer.revendor import plan_revendor, revendor

    framework_pkg = Path(evalglass.__file__).resolve().parent
    host = Path(root)
    if dry_run:
        return _emit(
            plan_revendor(framework_pkg, host, framework_version=evalglass.__version__).to_dict()
        )
    try:
        plan = revendor(
            framework_pkg, host, framework_version=evalglass.__version__, confirm=confirm
        )
    except InstallerError as exc:
        # A refused clobber is a deliberate stop, not a crash — report it and exit non-zero.
        print(f"revendor refused: {exc}", file=sys.stderr)
        return 1
    return _emit(plan.to_dict())


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        return _discover(args.root)
    if args.command == "install":
        return _install(args.root)
    if args.command == "revendor":
        return _revendor(args.root, dry_run=args.dry_run, confirm=args.confirm)
    return _plan(args.root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
