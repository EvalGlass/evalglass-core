"""EGP-P1-1: the bundled integration launcher runs the bundled skill and fails closed on setup.

`bin/evalglass-launch` lets a marketplace-only user drive the integration-time skill without a
`pip install`. It must resolve the plugin root (from `${CLAUDE_PLUGIN_ROOT}` or its own location),
forward arguments to `python -m evalglass.installer`, and report a missing bundled framework as a
*setup* error (exit 2) — never an evaluation result. It is never referenced by host runtime/CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.plugin.conftest import REPO_ROOT

_LAUNCH = REPO_ROOT / "bin" / "evalglass-launch"


def _env(*, plugin_root: str | None) -> dict[str, str]:
    # Put the active interpreter's dir first so the launcher's `python3` has the framework deps.
    env = {**os.environ, "PATH": f"{os.path.dirname(sys.executable)}:{os.environ.get('PATH', '')}"}
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    if plugin_root is not None:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    return env


def test_launcher_executable() -> None:
    assert os.access(_LAUNCH, os.X_OK), "bin/evalglass-launch must be executable"


def test_launcher_forwards_args_to_bundled_skill() -> None:
    result = subprocess.run(  # noqa: S603 — fixed absolute path, no shell, test-only
        [str(_LAUNCH), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(plugin_root=str(REPO_ROOT)),
        check=False,
    )
    assert result.returncode == 0, f"launcher --help failed: {result.stderr!r}"
    out = (result.stdout + result.stderr).lower()
    for sub in ("discover", "plan", "install", "revendor"):
        assert sub in out, f"launcher did not forward to the bundled skill (missing {sub!r})"


def test_launcher_derives_root_from_location() -> None:
    """With CLAUDE_PLUGIN_ROOT unset, the launcher derives the plugin root from its own path."""
    result = subprocess.run(  # noqa: S603 — fixed absolute path, no shell, test-only
        [str(_LAUNCH), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(plugin_root=None),
        check=False,
    )
    assert result.returncode == 0, f"launcher should self-locate the plugin root: {result.stderr!r}"


def test_launcher_missing_root_is_setup_error(tmp_path: Path) -> None:
    missing_root = tmp_path / "no-such-plugin-root"  # private tmp dir; has no src/evalglass
    result = subprocess.run(  # noqa: S603 — fixed absolute path, no shell, test-only
        [str(_LAUNCH), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(plugin_root=str(missing_root)),
        check=False,
    )
    assert result.returncode == 2, "missing bundled framework must exit 2 (setup error)"
    assert "setup error" in result.stderr.lower()


def test_launcher_runs_read_only_discover() -> None:
    result = subprocess.run(  # noqa: S603 — fixed absolute path, no shell, test-only
        [str(_LAUNCH), "discover", "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=_env(plugin_root=str(REPO_ROOT)),
        check=False,
    )
    assert result.returncode == 0, f"launcher discover regressed: {result.stderr!r}"
