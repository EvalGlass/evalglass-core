"""EGP-P3-5: runtime-after-removal holds *across* runtimes.

A Codex user gets the same vendored, skill-independent ``evals/_evalglass/`` runtime as a Claude
user (plan §8.6; ADR 0023). The plugin is never referenced by the host, so the verdict cannot
depend on *which* runtime installed it. This strengthens the single-runtime deletion-invariant
(``test_first_run_e2e.py``) into a cross-runtime proof:

* the typed ``VerdictPayload`` is **byte-identical** whether the host was installed by Claude
  (``CLAUDE_PLUGIN_ROOT`` set), by Codex (``CODEX_PLUGIN_ROOT`` set), or with neither present;
* the generated host tree carries **no** runtime-specific token for either runtime.

The *live* Codex trigger transcript is a maintainer acceptance probe, not a unit test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import evalglass
from evalglass.installer.scaffold import scaffold
from evalglass.installer.vendor import vendor

_FRAMEWORK_PKG = Path(evalglass.__file__).resolve().parent
_FRAMEWORK_SRC = _FRAMEWORK_PKG.parent
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def _install(host: Path) -> None:
    host.mkdir(parents=True, exist_ok=True)
    vendor(_FRAMEWORK_PKG, host, framework_version="1.0.0", source_ref="test")
    scaffold(host)


def _run(host: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), **extra_env}
    argv = [
        sys.executable,
        "-m",
        "_evalglass.harness.cli",
        "run",
        "--config",
        "evals/evalglass.yaml",
    ]
    return subprocess.run(  # noqa: S603 — fixed interpreter + module, no shell, test-only
        argv,
        cwd=host,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def _verdict(host: Path) -> dict[str, Any]:
    cards = list((host / "evals").rglob("scorecard.json"))
    assert cards, "no scorecard.json was written by the vendored run"
    data: dict[str, Any] = json.loads(cards[0].read_text(encoding="utf-8"))
    verdict: dict[str, Any] = data["verdict"]
    return verdict


def test_verdict_identical_across_runtimes(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host)
    vendored = str(host / "evals")
    installed_pythonpath = f"{vendored}{os.pathsep}{_FRAMEWORK_SRC}"

    envs = {
        "claude_installed": {
            "PYTHONPATH": installed_pythonpath,
            "CLAUDE_PLUGIN_ROOT": str(_PLUGIN_ROOT),
        },
        "codex_installed": {
            "PYTHONPATH": installed_pythonpath,
            "CODEX_PLUGIN_ROOT": str(_PLUGIN_ROOT),
        },
        "removed": {"PYTHONPATH": vendored},
    }

    verdicts: dict[str, str] = {}
    for label, env in envs.items():
        result = _run(host, env)
        assert result.returncode == 0, f"[{label}] run failed: {result.stderr}"
        verdicts[label] = json.dumps(_verdict(host), sort_keys=True)

    distinct = set(verdicts.values())
    assert len(distinct) == 1, (
        "VerdictPayload differs across runtimes — cross-runtime independence violated:\n"
        + "\n".join(f"  {k}: {v}" for k, v in verdicts.items())
    )


def test_host_tree_is_runtime_agnostic(tmp_path: Path) -> None:
    """Neither runtime's tokens may appear anywhere in the generated host tree."""
    host = tmp_path / "host"
    _install(host)
    forbidden = (
        "CLAUDE_PLUGIN_ROOT",
        "CODEX_PLUGIN_ROOT",
        ".claude-plugin",
        ".codex-plugin",
        "evalglass-launch",
    )
    offenders: list[str] = []
    for path in (host / "evals").rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(host)}: {token!r}")
    assert not offenders, "host tree references a runtime-specific token:\n" + "\n".join(offenders)
