"""Slice 8 (SG-P1-4): generated-authority / host-owned guard tests.

Sensitivity: a new/modified generated-authority file (baselines/calibration/
thresholds) without an approval marker FAILs; modifying or deleting a host-owned
file FAILs. Specificity: an approved authority file passes; adding a new
host-owned file passes; ordinary code passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.detectors import generated_authority
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return tmp_path


def _write(ws: Path, rel: str, content: str) -> None:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _file(rel: str, change_type: str = "modified", old_path: str | None = None) -> ChangedFile:
    return ChangedFile(
        path=rel,
        change_type=change_type,
        old_path=old_path,
        is_binary=False,
        added_lines=((1, 1),),
        is_untracked=False,
    )


def _run(ws: Path, *files: ChangedFile) -> generated_authority.DetectorResult:
    pack = DiffPack(base_ref="b", head_ref="WORKTREE", files=files)
    return generated_authority.run(pack, load_policy(FAST_POLICY), ws)


def _rules(result: generated_authority.DetectorResult) -> set[str]:
    return {f.rule_id for f in result.findings}


# ----- generated authority ---------------------------------------------------


def test_unmarked_generated_authority_fails(ws: Path) -> None:
    _write(ws, "evals/baselines/main.json", '{"score": 0.9}\n')
    result = _run(ws, _file("evals/baselines/main.json", "added"))
    assert "generated.no_unmarked_authority" in _rules(result)


def test_approved_generated_authority_passes(ws: Path) -> None:
    _write(ws, "evals/baselines/main.json", '{"approved_by": "alice", "score": 0.9}\n')
    result = _run(ws, _file("evals/baselines/main.json", "added"))
    assert result.findings == []


def test_marker_comment_generated_authority_passes(ws: Path) -> None:
    _write(ws, "evals/calibration/judge.json", '{"x": 1}\n# evalglass: approved by bob\n')
    result = _run(ws, _file("evals/calibration/judge.json", "modified"))
    assert result.findings == []


def test_deleting_generated_authority_not_flagged(ws: Path) -> None:
    result = _run(ws, _file("evals/baselines/main.json", "deleted"))
    assert result.findings == []


# ----- host-owned overwrite --------------------------------------------------


def test_modifying_host_owned_fails(ws: Path) -> None:
    _write(ws, "evals/datasets/gold.jsonl", '{"q": 1}\n')
    result = _run(ws, _file("evals/datasets/gold.jsonl", "modified"))
    assert "generated.no_host_owned_overwrite" in _rules(result)


def test_deleting_host_owned_fails(ws: Path) -> None:
    result = _run(ws, _file("evals/rubrics/tone.md", "deleted"))
    assert "generated.no_host_owned_overwrite" in _rules(result)


def test_adding_new_host_owned_passes(ws: Path) -> None:
    _write(ws, "evals/datasets/new.jsonl", '{"q": 2}\n')
    result = _run(ws, _file("evals/datasets/new.jsonl", "added"))
    assert result.findings == []


# ----- specificity + ledger --------------------------------------------------


def test_ordinary_code_passes(ws: Path) -> None:
    _write(ws, "src/evalglass/core/scores.py", "X = 1\n")
    result = _run(ws, _file("src/evalglass/core/scores.py", "modified"))
    assert result.findings == []


def test_detector_emits_ledger_entry(ws: Path) -> None:
    _write(ws, "README.md", "hi\n")
    result = _run(ws, _file("README.md", "modified"))
    assert any(e.tool == "generated_authority" and e.network == "disabled" for e in result.ledger)


# ----- review hardening ------------------------------------------------------


def test_rename_into_host_owned_allowed(ws: Path) -> None:
    # git mv examples/sample.jsonl -> evals/datasets/new.jsonl is an add, not a clobber.
    result = _run(
        ws, _file("evals/datasets/new.jsonl", "renamed", old_path="examples/sample.jsonl")
    )
    assert "generated.no_host_owned_overwrite" not in _rules(result)


def test_rename_within_host_owned_flagged(ws: Path) -> None:
    result = _run(ws, _file("evals/datasets/b.jsonl", "renamed", old_path="evals/datasets/a.jsonl"))
    assert "generated.no_host_owned_overwrite" in _rules(result)


def test_type_change_host_owned_flagged(ws: Path) -> None:
    result = _run(ws, _file("evals/datasets/gold.jsonl", "type_changed"))
    assert "generated.no_host_owned_overwrite" in _rules(result)


def test_type_change_generated_authority_requires_approval(ws: Path) -> None:
    _write(ws, "evals/baselines/x.json", '{"score": 1}\n')
    result = _run(ws, _file("evals/baselines/x.json", "type_changed"))
    assert "generated.no_unmarked_authority" in _rules(result)


def test_symlink_authority_not_approved_via_target(ws: Path) -> None:
    _write(ws, "approved_elsewhere.json", '{"approved_by": "x"}\n')
    (ws / "evals" / "baselines").mkdir(parents=True)
    (ws / "evals" / "baselines" / "main.json").symlink_to(ws / "approved_elsewhere.json")
    result = _run(ws, _file("evals/baselines/main.json", "added"))
    assert "generated.no_unmarked_authority" in _rules(result)
