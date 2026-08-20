"""The CLI module entrypoint must be free of the benign-but-noisy runpy double-import warning.

``python -m evalglass.harness.cli`` used to emit a ``RuntimeWarning`` on every run (quickstart,
run, CI) because the ``harness`` package ``__init__`` eagerly imported ``cli``, putting it in
``sys.modules`` before runpy could execute it as ``__main__``. Deferring that import (PEP 562)
keeps ``from evalglass.harness import main`` working while removing the warning. This is a
user-facing DX guard: the documented commands all use ``-m ...harness.cli``.
"""

from __future__ import annotations

import subprocess
import sys


def test_importing_harness_package_does_not_eagerly_load_cli() -> None:
    """Importing the package must NOT import its ``cli`` submodule (the root cause of the warning),
    yet ``main``/``build_parser`` must still resolve lazily off the package."""
    code = (
        "import sys, evalglass.harness\n"
        "assert 'evalglass.harness.cli' not in sys.modules, 'cli was eagerly imported'\n"
        "from evalglass.harness import main, build_parser\n"
        "assert callable(main) and callable(build_parser)\n"
        "assert 'evalglass.harness.cli' in sys.modules, 'lazy access should load cli'\n"
    )
    result = subprocess.run(  # noqa: S603 — fixed interpreter, no shell, test-only
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_cli_module_entrypoint_emits_no_runpy_runtimewarning() -> None:
    """``python -W error::RuntimeWarning -m evalglass.harness.cli --help`` must exit cleanly — if
    the runpy double-import warning fired it would be promoted to an error."""
    argv = [sys.executable, "-W", "error::RuntimeWarning", "-m", "evalglass.harness.cli", "--help"]
    result = subprocess.run(  # noqa: S603 — fixed interpreter + module, no shell, test-only
        argv, capture_output=True, text=True, check=False
    )
    # --help exits 0 via argparse; a promoted RuntimeWarning would make this non-zero.
    assert result.returncode == 0, result.stderr
    assert "RuntimeWarning" not in result.stderr
    assert "found in sys.modules" not in result.stderr
