"""EGP-P3-3: the multi-runtime version-bump config + audit script.

One repo means one version line (ADR 0022/0023). ``.version-bump.json`` declares every
version-bearing surface; ``scripts/bump-version.sh --check`` fails on any drift and ``--audit``
reports all surfaces plus the expected git tag. The script writes only declared packaging files —
never a host-owned runtime tree (``evals/``).

These tests drive the real script as a subprocess (the only honest proof it works) against the
repo and against a perturbed temp fixture (the negative control).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tests.plugin.conftest import REPO_ROOT

_CONFIG = REPO_ROOT / ".version-bump.json"
_SCRIPT = REPO_ROOT / "scripts" / "bump-version.sh"

#: The in-repo version surfaces — must equal what test_version_alignment enforces.
_EXPECTED_SOURCES = {
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "pyproject.toml",
    "src/evalglass/__init__.py",
    "CITATION.cff",
}


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    argv = [str(_SCRIPT), *args]
    if root is not None:
        argv += ["--root", str(root)]
    return subprocess.run(  # noqa: S603 — fixed absolute script path, no shell, test-only
        argv, capture_output=True, text=True, timeout=30, check=False
    )


def _sources() -> list[dict[str, str]]:
    data = json.loads(_CONFIG.read_text(encoding="utf-8"))
    return [{k: str(v) for k, v in entry.items()} for entry in data["version_sources"]]


def _diag(result: subprocess.CompletedProcess[str]) -> str:
    return f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_config_exists_and_lists_every_surface() -> None:
    assert _CONFIG.is_file(), ".version-bump.json must exist (P3-3)"
    paths = {s["path"] for s in _sources()}
    assert paths == _EXPECTED_SOURCES, f"version_sources {paths} != alignment set"


def test_config_declares_tag_format_and_never_touches_host() -> None:
    data = json.loads(_CONFIG.read_text(encoding="utf-8"))
    assert "{version}" in str(data["tag_format"]), "tag_format must template the version"
    for src in _sources():
        assert not src["path"].startswith("evals/"), (
            "version-bump must never target a host-owned/vendored tree"
        )


def test_script_is_executable() -> None:
    assert _SCRIPT.is_file(), "scripts/bump-version.sh must exist"
    assert os.access(_SCRIPT, os.X_OK), "bump-version.sh must be executable"


def test_check_passes_on_aligned_repo() -> None:
    result = _run("--check")
    assert result.returncode == 0, "--check should pass on an aligned repo" + _diag(result)


def test_audit_reports_all_surfaces_and_tag() -> None:
    result = _run("--audit")
    assert result.returncode == 0, "--audit should exit 0" + _diag(result)
    for path in _EXPECTED_SOURCES:
        assert path in result.stdout, f"--audit output missing surface {path!r}"
    assert "v0.1.0" in result.stdout, "--audit must report the expected git tag (v<version>)"


def test_check_detects_drift_negative_control(tmp_path: Path) -> None:
    """Copy the real version files into a temp root, perturb one, and prove --check fails."""
    for rel in _EXPECTED_SOURCES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dst)
    codex = tmp_path / ".codex-plugin" / "plugin.json"
    data = json.loads(codex.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    codex.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    result = _run("--check", root=tmp_path)
    assert result.returncode != 0, "--check must fail on drift" + _diag(result)
    assert "9.9.9" in result.stdout, "drift report should surface the mismatched version"


def test_check_with_matching_expect_passes() -> None:
    result = _run("--check", "--expect", "0.1.0")
    assert result.returncode == 0, "--expect 0.1.0 should pass" + _diag(result)


def test_check_with_mismatched_expect_fails() -> None:
    result = _run("--check", "--expect", "9.9.9")
    assert result.returncode != 0, "--expect 9.9.9 must fail against a 0.1.0 repo"
