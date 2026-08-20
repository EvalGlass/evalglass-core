"""EGP-P0-5 / EGP-P0-8: the direct skill CLI path is unchanged (additive plugin, plan §7.4).

A marketplace plugin is an additive convenience layer. The pre-existing direct integration path —
``python -m evalglass.installer <discover|plan|install|revendor>`` and the console entry points —
must keep working exactly as before, so existing users and the runtime-independence guarantee are
not disturbed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib

from tests.plugin.conftest import REPO_ROOT

_SRC = REPO_ROOT / "src"


def _run_skill(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    return subprocess.run(  # noqa: S603 — fixed interpreter, no shell, test-only
        [sys.executable, "-m", "evalglass.installer", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )


def test_skill_module_help_still_works() -> None:
    result = _run_skill("--help")
    assert result.returncode == 0, (
        f"`python -m evalglass.installer --help` failed: {result.stderr!r}"
    )
    help_text = (result.stdout + result.stderr).lower()
    for sub in ("discover", "plan", "install", "revendor"):
        assert sub in help_text, (
            f"skill subcommand {sub!r} missing from help — migration regression"
        )


def test_skill_discover_runs_read_only() -> None:
    """`discover` is read-only and must still run against the repo without error."""
    result = _run_skill("discover", "--root", str(REPO_ROOT))
    assert result.returncode == 0, f"`evalglass.installer discover` regressed: {result.stderr!r}"


def test_console_entry_points_unchanged() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["evalglass"] == "evalglass.harness.cli:main"
    assert scripts["evalglass-install"] == "evalglass.installer.cli:main"
