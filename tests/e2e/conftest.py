"""Shared black-box e2e fixtures (EG-AT6-1; alignment plan §F).

Journeys observe the product through its real surfaces with a controlled, hermetic environment and
no ambient credentials:

* ``make_host`` / ``installed_host`` — a host with a **real** vendored runtime in a known authority
  state (reuses the AT0 ``make_vendored_host`` install path); ``vendored_run`` invokes that vendored
  runtime in a clean subprocess (target T2, ``PYTHONPATH=evals``);
* ``bundled_example_run`` — runs the bundled quickstart through the framework CLI (target T3,
  pre-install) in a tmp copy with a scrubbed environment.

All fixtures are ``tmp_path``-isolated and run no network (the autouse guard stays armed; subprocess
children inherit a minimal PATH and a scrubbed HOME).
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import evalglass
from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost, make_vendored_host

#: examples/quickstart in the framework repo (the T3 bundled example).
_QUICKSTART = Path(evalglass.__file__).resolve().parents[2] / "examples" / "quickstart"
#: The framework source root for the T3 (pre-install) run.
_SRC_ROOT = Path(evalglass.__file__).resolve().parents[1]


def _safe_path() -> str:
    py_dir = str(Path(sys.executable).parent) if sys.executable else ""
    return os.pathsep.join(p for p in (py_dir, "/usr/bin", "/bin") if p)


@pytest.fixture
def make_host(tmp_path: Path) -> Callable[..., VendoredHost]:
    """Factory for vendored hosts in any pre-baked authority state (tmp_path-isolated)."""
    counter = itertools.count()

    def _make(
        authority_state: AuthorityState | str = AuthorityState.FRESH_INFORMATIONAL,
        *,
        with_diluting_trace: bool = False,
    ) -> VendoredHost:
        return make_vendored_host(
            tmp_path,
            f"host{next(counter)}",
            authority_state=authority_state,
            with_diluting_trace=with_diluting_trace,
        )

    return _make


@pytest.fixture
def installed_host(make_host: Callable[..., VendoredHost]) -> VendoredHost:
    """A freshly-installed host — the common first-run, informational starting point."""
    return make_host(AuthorityState.FRESH_INFORMATIONAL)


@pytest.fixture
def vendored_run() -> Callable[..., CliResult]:
    """Run the vendored runtime (target T2) and read back the typed artifacts."""

    def _run(host: VendoredHost, *args: str, plugin_present: bool = False) -> CliResult:
        return host.run(list(args), plugin_present=plugin_present)

    return _run


@pytest.fixture
def bundled_example_run(tmp_path: Path) -> Callable[..., CliResult]:
    """Run the bundled quickstart through the framework CLI (target T3, pre-install)."""
    counter = itertools.count()

    def _run(*args: str) -> CliResult:
        root = tmp_path / f"quickstart{next(counter)}"  # fresh copy per invocation (reentrant)
        shutil.copytree(_QUICKSTART, root)
        cli_args = list(args) or ["run", "--config", "evals/evalglass.yaml"]
        env = {
            "PATH": _safe_path(),
            "PYTHONPATH": str(_SRC_ROOT),
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C",
            "HOME": str(root),
        }
        completed = subprocess.run(  # noqa: S603 — fixed argv, shell=False, controlled env
            [sys.executable, "-m", "evalglass.harness.cli", *cli_args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        reports = root / "evals" / "reports" / "quickstart"
        report_md = reports / "report.md"
        return CliResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            scorecard=_read_json(reports / "scorecard.json"),
            runrecord=_read_json(reports / "runrecord.json"),
            report=report_md.read_text(encoding="utf-8") if report_md.is_file() else None,
        )

    return _run


def _read_json(path: Path) -> dict[str, object] | None:
    import json

    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None
