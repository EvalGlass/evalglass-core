"""Slice 9 (SG-P1-5): CI/script guard detector tests.

Sensitivity: on changed CI workflows and shell scripts, grep-based verdicts,
gate failure-suppression (gate || true / || exit 0), and continue-on-error.
Specificity: normal CI steps and ordinary cleanup (`rm ... || true`) do not trip,
and non-CI/non-script files are ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.detectors import ci_script_guard
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return tmp_path


def _write(ws: Path, rel: str, content: str) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return rel


def _pack(rel: str) -> DiffPack:
    return DiffPack(
        base_ref="b",
        head_ref="WORKTREE",
        files=(
            ChangedFile(
                path=rel,
                change_type="added",
                old_path=None,
                is_binary=False,
                added_lines=((1, 10_000),),
                is_untracked=False,
            ),
        ),
    )


def _run(ws: Path, rel: str) -> ci_script_guard.DetectorResult:
    return ci_script_guard.run(_pack(rel), load_policy(FAST_POLICY), ws)


def _rules(result: ci_script_guard.DetectorResult) -> set[str]:
    return {f.rule_id for f in result.findings}


# ----- sensitivity -----------------------------------------------------------


def test_grep_based_verdict_fails(ws: Path) -> None:
    rel = _write(ws, "ci/gate.sh", "#!/bin/sh\ngrep -q PASS report.txt && exit 0\n")
    assert "ci.no_verdict_spoof" in _rules(_run(ws, rel))


def test_gate_failure_suppression_fails(ws: Path) -> None:
    rel = _write(ws, "run_checks.sh", "#!/bin/sh\npytest tests/ || true\n")
    assert "ci.no_verdict_spoof" in _rules(_run(ws, rel))


def test_gate_exit0_suppression_fails(ws: Path) -> None:
    rel = _write(
        ws,
        ".github/workflows/ci.yml",
        "jobs:\n  x:\n    steps:\n      - run: scan-gate run || exit 0\n",
    )
    assert "ci.no_verdict_spoof" in _rules(_run(ws, rel))


def test_continue_on_error_warns(ws: Path) -> None:
    rel = _write(
        ws,
        ".github/workflows/ci.yml",
        "jobs:\n  x:\n    steps:\n      - run: pytest\n        continue-on-error: true\n",
    )
    result = _run(ws, rel)
    assert "ci.continue_on_error" in _rules(result)
    assert all(
        f.severity.value == "warn" for f in result.findings if f.rule_id == "ci.continue_on_error"
    )


# ----- specificity -----------------------------------------------------------


def test_normal_ci_step_passes(ws: Path) -> None:
    rel = _write(
        ws, ".github/workflows/ci.yml", "jobs:\n  x:\n    steps:\n      - run: uv run pytest\n"
    )
    assert _run(ws, rel).findings == []


def test_ordinary_cleanup_or_true_passes(ws: Path) -> None:
    rel = _write(ws, "setup.sh", "#!/bin/sh\nrm -f /tmp/scratch || true\n")
    assert _run(ws, rel).findings == []


def test_non_ci_python_file_ignored(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/x.py", "x = 1  # pytest || true\n")
    assert _run(ws, rel).findings == []


def test_detector_emits_ledger_entry(ws: Path) -> None:
    rel = _write(ws, "ok.sh", "#!/bin/sh\necho hi\n")
    result = _run(ws, rel)
    assert any(e.tool == "ci_script_guard" and e.network == "disabled" for e in result.ledger)


# ----- review hardening ------------------------------------------------------


def test_yaml_comment_or_name_not_flagged(ws: Path) -> None:
    rel = _write(
        ws,
        ".github/workflows/ci.yml",
        "jobs:\n  x:\n    steps:\n      - name: do not use pytest || true\n"
        "      - run: uv run pytest\n",
    )
    assert _run(ws, rel).findings == []


def test_block_scalar_run_body_flagged(ws: Path) -> None:
    rel = _write(
        ws,
        ".github/workflows/ci.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n          pytest || true\n      - name: next\n",
    )
    assert "ci.no_verdict_spoof" in _rules(_run(ws, rel))


def test_rename_into_ci_scans_full_content(ws: Path) -> None:
    _write(
        ws,
        ".github/workflows/ci.yml",
        "jobs:\n  x:\n    steps:\n      - run: scan-gate run || exit 0\n",
    )
    pack = DiffPack(
        base_ref="b",
        head_ref="WORKTREE",
        files=(
            ChangedFile(
                path=".github/workflows/ci.yml",
                change_type="renamed",
                old_path="archive/old.yml",  # source not in a guarded group
                is_binary=False,
                added_lines=(),  # pure rename -> git -M reports no added lines
                is_untracked=False,
            ),
        ),
    )
    result = ci_script_guard.run(pack, load_policy(FAST_POLICY), ws)
    assert "ci.no_verdict_spoof" in _rules(result)
