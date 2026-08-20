"""EGP-P1-6 / P1-11 / P1-12: the first-run journey produces honest evidence, and removing the
plugin changes no verdict.

Hermetic end-to-end: vendor + scaffold a throwaway host, run the **vendored** runtime in a clean
subprocess, and assert (a) a populated **informational** Scorecard with real non-reference signal,
(b) the generated host `evals/` tree references neither the launcher nor `${CLAUDE_PLUGIN_ROOT}`,
and (c) the typed `VerdictPayload` is **byte-identical** whether or not the plugin/framework are on
the path (the deletion-invariant — strengthened from "still runs" to verdict identity).
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
_FRAMEWORK_SRC = _FRAMEWORK_PKG.parent  # the dir containing the `evalglass` package


def _install(host: Path) -> None:
    host.mkdir(parents=True, exist_ok=True)
    vendor(_FRAMEWORK_PKG, host, framework_version="1.0.0", source_ref="test")
    scaffold(host)


def _run(host: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "_evalglass.harness.cli", "run", "--config", "evals/evalglass.yaml"],
        cwd=host,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def _vendored_env(host: Path) -> dict[str, str]:
    """Post-removal state: only the host's evals/ on the path (no framework, no plugin)."""
    return {"PYTHONPATH": str(host / "evals"), "PATH": os.environ.get("PATH", "")}


def _installed_state_env(host: Path) -> dict[str, str]:
    """Installed state: framework src on the path and CLAUDE_PLUGIN_ROOT set (plugin present)."""
    return {
        "PYTHONPATH": f"{host / 'evals'}{os.pathsep}{_FRAMEWORK_SRC}",
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(Path(__file__).resolve().parents[2]),
    }


def _read_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _scorecard(host: Path) -> dict[str, Any]:
    cards = list((host / "evals").rglob("scorecard.json"))
    assert cards, "no scorecard.json was written by the vendored run"
    return _read_json(cards[0])


def _runrecord(host: Path) -> dict[str, Any]:
    recs = list((host / "evals").rglob("runrecord.json"))
    assert recs, "no runrecord.json was written by the vendored run"
    return _read_json(recs[0])


def test_first_run_is_populated_and_informational(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host)
    result = _run(host, _vendored_env(host))
    assert result.returncode == 0, result.stderr
    assert "informational" in result.stdout.lower()

    scorecard = _scorecard(host)
    assert scorecard["verdict"]["verdict"] == "informational"
    assert scorecard["verdict"]["ci_should_fail"] is False

    # Real, populated non-reference signal — at least one structural_shape/field_presence score.
    scores = _runrecord(host)["scores"]
    non_ref = [s for s in scores if s["metric"] in {"structural_shape", "field_presence"}]
    assert non_ref, "expected the non-reference built-ins to be wired"
    assert any(s["status"] == "scored" for s in non_ref), (
        "the first run must produce real non-reference signal, not only blocked metrics"
    )
    # And no non-scored metric was coerced to a 0.0 value.
    for s in scores:
        if s["status"] != "scored":
            assert s["value"] is None, f"{s['metric']} is {s['status']} but carries a value"


def test_generated_host_tree_has_no_plugin_reference(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host)
    forbidden = ("evalglass-launch", "CLAUDE_PLUGIN_ROOT", "${CLAUDE_PLUGIN_ROOT}")
    # Host-owned scaffolded files (not the vendored _evalglass tree).
    host_owned = [
        host / "evals" / "evalglass.yaml",
        host / "evals" / "authority.json",
        host / "evals" / "ci" / "github-actions.yml",
        host / "evals" / "README.md",
    ]
    for path in host_owned:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} references the plugin ({token!r})"


def test_deletion_invariant_verdict_identity(tmp_path: Path) -> None:
    """Removing the plugin/framework must not change a single typed verdict field."""
    host = tmp_path / "host"
    _install(host)

    # Run A: plugin & framework present (installed state).
    assert _run(host, _installed_state_env(host)).returncode == 0
    verdict_present = _scorecard(host)["verdict"]

    # Run B: plugin & framework removed from the path (post-removal state).
    assert _run(host, _vendored_env(host)).returncode == 0
    verdict_removed = _scorecard(host)["verdict"]

    # Byte-identical typed verdict payload — not merely "still runs".
    assert json.dumps(verdict_present, sort_keys=True) == json.dumps(
        verdict_removed, sort_keys=True
    ), "removing the plugin/framework changed the verdict payload — runtime independence violated"


def _artifact_text(host: Path, name: str) -> str:
    matches = list((host / "evals").rglob(name))
    assert matches, f"no {name} was written by the vendored run"
    return matches[0].read_text(encoding="utf-8")


def test_deletion_invariant_artifacts_byte_identical(tmp_path: Path) -> None:
    """FS-DEL-2: the whole scorecard.json AND runrecord.json are byte-identical with the
    plugin root set vs unset — the plugin/framework is delivery, never meaning."""
    host = tmp_path / "host"
    _install(host)

    # Run A: installed state (framework on path, CLAUDE_PLUGIN_ROOT set).
    assert _run(host, _installed_state_env(host)).returncode == 0
    scorecard_present = _artifact_text(host, "scorecard.json")
    runrecord_present = _artifact_text(host, "runrecord.json")

    # Run B: post-removal state (only the vendored evals/ on the path, no plugin root).
    assert _run(host, _vendored_env(host)).returncode == 0
    scorecard_removed = _artifact_text(host, "scorecard.json")
    runrecord_removed = _artifact_text(host, "runrecord.json")

    assert scorecard_present == scorecard_removed, (
        "scorecard.json differs with the plugin root set vs unset"
    )
    assert runrecord_present == runrecord_removed, (
        "runrecord.json differs with the plugin root set vs unset"
    )
