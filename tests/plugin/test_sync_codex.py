"""EGP-P3-4: the deterministic sync-to-Codex script (hermetic core).

The Codex marketplace copy is produced from the canonical repo by
``scripts/sync-to-codex-plugin.sh`` (plan §8.4; ADR 0023). The network-free heart of the tool is
``--stage <dir>``: it assembles the Codex plugin payload (the shared ``skills/`` tree, the
committed ``.codex-plugin/`` manifest, and the ``AGENTS.md`` bootstrap) while excluding all
runtime-specific infra (``src/``, ``.claude-plugin/``, ``hooks/``, ``scripts/``, ``tests/``, dev
gates, root build-guide). Two properties are proven:

* **fidelity** — the staged ``skills/`` is byte-identical to the canonical source (no fork/drift);
* **determinism** — the same source produces a byte-identical stage every run (so two runs verify
  the tool itself, plan §8.4).

The *live* clone/commit/PR to the Codex marketplace fork is a maintainer step (needs the fork +
``gh`` auth + the open Codex-fork question); it is not exercised here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.plugin.conftest import REPO_ROOT

_SCRIPT = REPO_ROOT / "scripts" / "sync-to-codex-plugin.sh"

_MUST_INCLUDE = (
    "skills/evalglass/SKILL.md",
    ".codex-plugin/plugin.json",
    "AGENTS.md",
)
_MUST_EXCLUDE = (
    "src",
    ".claude-plugin",
    "hooks",
    "scripts",
    "tests",
    "CLAUDE.md",
    "docs",
    ".github",
)


def _stage(dest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed absolute script path, no shell, test-only
        [str(_SCRIPT), "--stage", str(dest)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_script_exists_and_is_executable() -> None:
    assert _SCRIPT.is_file(), "scripts/sync-to-codex-plugin.sh must exist (P3-4)"
    assert os.access(_SCRIPT, os.X_OK), "sync script must be executable"


def test_help_exits_zero() -> None:
    result = subprocess.run(  # noqa: S603 — fixed absolute script path, no shell, test-only
        [str(_SCRIPT), "--help"], capture_output=True, text=True, timeout=20, check=False
    )
    assert result.returncode == 0, f"--help should exit 0:\n{result.stderr}"


def test_stage_includes_codex_payload(tmp_path: Path) -> None:
    dest = tmp_path / "stage"
    result = _stage(dest)
    assert result.returncode == 0, f"--stage failed:\n{result.stdout}\n{result.stderr}"
    for rel in _MUST_INCLUDE:
        assert (dest / rel).exists(), f"staged Codex payload missing {rel!r}"


def test_stage_excludes_runtime_specific_infra(tmp_path: Path) -> None:
    dest = tmp_path / "stage"
    assert _stage(dest).returncode == 0
    for rel in _MUST_EXCLUDE:
        assert not (dest / rel).exists(), (
            f"runtime-specific path {rel!r} must not be synced into the Codex plugin"
        )


def test_staged_skills_are_byte_identical_to_canonical(tmp_path: Path) -> None:
    """Fidelity: the synced skills tree is a faithful copy of the one canonical source."""
    dest = tmp_path / "stage"
    assert _stage(dest).returncode == 0
    diff = subprocess.run(  # noqa: S603 — fixed args, no shell, test-only
        ["/usr/bin/diff", "-r", str(REPO_ROOT / "skills"), str(dest / "skills")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert diff.returncode == 0, f"staged skills/ drifted from canonical:\n{diff.stdout}"


def test_stage_is_deterministic(tmp_path: Path) -> None:
    """Determinism: the same source yields a byte-identical stage (two runs verify the tool)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert _stage(a).returncode == 0
    assert _stage(b).returncode == 0
    diff = subprocess.run(  # noqa: S603 — fixed args, no shell, test-only
        ["/usr/bin/diff", "-r", str(a), str(b)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert diff.returncode == 0, f"sync is not deterministic:\n{diff.stdout}"
