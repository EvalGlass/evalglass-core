"""S4 (EG-M3-4) — the vendored runtime runs after the skill and agent are gone.

The single hardest M3 invariant (P13; ADR 0010): once installed, the vendored
``_evalglass`` runtime runs with **no** installed framework and **no** ``skill/``. This
proves it through a clean subprocess against a freshly installed host — only the host's
``evals/`` on the import path, the ``_evalglass`` namespace resolving solely to the
vendored copy (which, per S2's no-residual-imports test, imports nothing named
``evalglass``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import evalglass
from evalglass.installer.scaffold import scaffold
from evalglass.installer.vendor import vendor

_FRAMEWORK_PKG = Path(evalglass.__file__).resolve().parent


def _install(host: Path) -> None:
    host.mkdir(parents=True, exist_ok=True)
    vendor(_FRAMEWORK_PKG, host, framework_version="1.0.0", source_ref="test")
    scaffold(host)


def _evals_env(host: Path) -> dict[str, str]:
    # Only the host's evals/ on the import path — so `_evalglass` resolves to the vendored copy.
    return {"PYTHONPATH": str(host / "evals"), "PATH": os.environ.get("PATH", "")}


def test_vendored_runtime_first_run_is_informational(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host)
    result = subprocess.run(
        [sys.executable, "-m", "_evalglass.harness.cli", "run", "--config", "evals/evalglass.yaml"],
        cwd=host,
        capture_output=True,
        text=True,
        env=_evals_env(host),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "informational" in result.stdout


def test_vendored_tree_imports_no_framework(tmp_path: Path) -> None:
    """Independence's static half: the vendored tree imports nothing named ``evalglass``.

    So even though the framework may be installed in this environment, the subprocess run
    above cannot bind it — every import resolves within the vendored ``_evalglass`` + stdlib.
    """
    host = tmp_path / "host"
    _install(host)
    offenders: list[str] = []
    for py in (host / "evals" / "_evalglass").rglob("*.py"):
        for line in py.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("from evalglass", "import evalglass")):
                offenders.append(f"{py.name}: {s}")
    assert not offenders, f"vendored runtime could bind the installed framework: {offenders}"


def test_skill_is_not_vendored(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host)
    assert not (host / "evals" / "_evalglass" / "skill").exists()


def test_vendored_runtime_does_not_import_skill(tmp_path: Path) -> None:
    """`_evalglass.installer` must not even be importable from the vendored tree."""
    host = tmp_path / "host"
    _install(host)
    spec_path = host / "evals" / "_evalglass" / "skill"
    assert not spec_path.exists()
    # And confirm via a subprocess resolving only the vendored tree.
    code = (
        "import sys, importlib.util; sys.path.insert(0, sys.argv[1]); "
        "print(importlib.util.find_spec('_evalglass.installer') is None)"
    )
    result = subprocess.run(  # noqa: S603 — fixed interpreter, no shell, test-only
        [sys.executable, "-c", code, str(host / "evals")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == "True", result.stdout + result.stderr
