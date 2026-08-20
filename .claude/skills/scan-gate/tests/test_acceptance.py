"""Slice 10: Layer-2 acceptance suite — the assembled skill, end to end.

Drives the real `scan-gate run` CLI against throwaway git repos and asserts:
clean diff -> PASS with zero false positives; a realistic multi-violation diff ->
FAIL with every expected detector firing (a silently-disabled detector would
fail this meta-test); a missing base ref -> BLOCKED; results are deterministic;
and the run is hermetic (every tool-ledger entry reports network=disabled).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.scan_gate import main

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parents[2]
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"

FAKE_AWS = "AKIA1234567890ABCDEF"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tools" / "check_core_isolation.py", repo / "tools" / "check_core_isolation.py"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _run(repo: Path, base: str, out: Path, *, head: str = "WORKTREE") -> int:
    return main(
        [
            "run",
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--profile",
            "fast",
            "--policy",
            str(FAST_POLICY),
            "--json",
            str(out),
        ]
    )


def test_clean_diff_passes_with_no_false_positives(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write(
        repo,
        "src/evalglass/core/scores.py",
        "from dataclasses import dataclass\n\n\n@dataclass\nclass Score:\n    value: float\n",
    )
    _write(
        repo,
        "src/evalglass/harness/report.py",
        "def render(scorecard):\n    return str(scorecard.verdict)\n",
    )
    out = tmp_path / "r.json"
    rc = _run(repo, base, out)
    result = json.loads(out.read_text())
    assert result["status"] == "PASS"
    assert result["findings"] == []
    assert rc == 0


def test_multi_violation_diff_fails_with_all_detectors(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write(repo, "src/evalglass/core/judge.py", "import openai\n\nX = 1\n")  # vendor import in core
    _write(repo, "config.py", f'AWS = "{FAKE_AWS}"\n')  # secret
    _write(repo, "evals/baselines/main.json", '{"score": 0.9}\n')  # unmarked authority
    _write(repo, "gate.sh", "#!/bin/sh\npytest || true\n")  # ci verdict spoof
    _write(repo, "Dockerfile", "FROM python:3.12-slim\n")  # manifest drift (warn)
    out = tmp_path / "r.json"
    rc = _run(repo, base, out)
    result = json.loads(out.read_text())
    rule_ids = {f["rule_id"] for f in result["findings"]}
    assert {
        "required.no_live_model_imports",
        "secrets.no_new_secrets",
        "generated.no_unmarked_authority",
        "ci.no_verdict_spoof",
        "manifest.review_required",
    } <= rule_ids
    assert result["status"] == "FAIL"  # FAIL present, nothing blocked
    assert rc == 1


def test_missing_base_ref_is_blocked(tmp_path: Path) -> None:
    repo, _ = _base_repo(tmp_path)
    out = tmp_path / "r.json"
    rc = _run(repo, "deadbeef" * 5, out)
    result = json.loads(out.read_text())
    assert result["status"] == "BLOCKED"
    assert rc == 2


def test_results_are_deterministic(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write(repo, "config.py", f'AWS = "{FAKE_AWS}"\n')
    _write(repo, "src/evalglass/core/judge.py", "import openai\n")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _run(repo, base, a)
    _run(repo, base, b)
    assert a.read_text() == b.read_text()


def test_run_is_hermetic_network_disabled(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write(repo, "config.py", f'AWS = "{FAKE_AWS}"\n')
    out = tmp_path / "r.json"
    _run(repo, base, out)
    result = json.loads(out.read_text())
    assert result["tool_ledger"]
    assert all(entry["network"] == "disabled" for entry in result["tool_ledger"])


def test_run_does_not_mutate_the_scanned_repo(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write(
        repo, "src/evalglass/core/judge.py", "import openai\n"
    )  # forces the core-isolation reuse path
    before = {p.relative_to(repo) for p in repo.rglob("*") if ".git" not in p.parts}
    _run(repo, base, tmp_path / "r.json")
    after = {p.relative_to(repo) for p in repo.rglob("*") if ".git" not in p.parts}
    assert after == before  # no .pyc / __pycache__ written into the subject


@pytest.mark.parametrize("missing", ["--policy", "--profile"])
def test_run_requires_core_args(tmp_path: Path, missing: str) -> None:
    repo, base = _base_repo(tmp_path)
    argv = [
        "run",
        "--repo",
        str(repo),
        "--base",
        base,
        "--profile",
        "fast",
        "--policy",
        str(FAST_POLICY),
    ]
    argv = [
        a for a in argv if a != missing and not (missing == "--policy" and a == str(FAST_POLICY))
    ]
    argv = [a for a in argv if not (missing == "--profile" and a == "fast")]
    with pytest.raises(SystemExit):
        main(argv)
