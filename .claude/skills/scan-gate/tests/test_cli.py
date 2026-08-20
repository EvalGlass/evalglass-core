"""Slice 2 (SG-P0-2): CLI tests for the `diff` subcommand.

The CLI is the single behavior source. `diff` builds the diff pack and writes it
as JSON (exit 0). A missing base ref fails closed: BLOCKED to stderr, non-zero
exit -- never silently treated as a clean scan.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.diffpack import DiffPack
from scripts.scan_gate import main


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo_with_change(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "a.py").write_text("x = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    return repo, base


def test_cli_diff_emits_pack(repo_with_change: tuple[Path, str], tmp_path: Path) -> None:
    repo, base = repo_with_change
    out = tmp_path / "pack.json"
    rc = main(["diff", "--repo", str(repo), "--base", base, "--head", "HEAD", "--out", str(out)])
    assert rc == 0
    pack = DiffPack.from_dict(json.loads(out.read_text()))
    assert any(f.path == "a.py" for f in pack.files)


def test_cli_missing_base_is_blocked(
    repo_with_change: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = repo_with_change
    rc = main(["diff", "--repo", str(repo), "--base", "deadbeef" * 5, "--head", "HEAD"])
    assert rc != 0
    assert "BLOCKED" in (capsys.readouterr().err)


def test_cli_unknown_subcommand_errors(repo_with_change: tuple[Path, str]) -> None:
    repo, _base = repo_with_change
    with pytest.raises(SystemExit):
        main(["frobnicate", "--repo", str(repo)])


_SKILL_ROOT = Path(__file__).resolve().parent.parent
_FAST_POLICY = _SKILL_ROOT / "policies" / "evalglass.fast.yml"


def test_cli_policy_valid(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["policy", "--policy", str(_FAST_POLICY), "--profile", "fast"])
    assert rc == 0
    assert '"status": "OK"' in capsys.readouterr().out


def test_cli_policy_unknown_profile_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["policy", "--policy", str(_FAST_POLICY), "--profile", "nope"])
    assert rc != 0
    assert "BLOCKED" in capsys.readouterr().err


def test_cli_policy_missing_file_blocked(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    rc = main(["policy", "--policy", str(tmp_path / "absent.yml")])
    assert rc != 0
    assert "BLOCKED" in capsys.readouterr().err
