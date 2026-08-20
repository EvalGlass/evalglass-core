"""Slice 6 (SG-P1-2): imports/effects detector tests.

The highest-value trust detector. Sensitivity: vendor SDK imports, effects, and
optional-lane imports in required-tier; verdict-literal logic in harness/adapters.
Specificity: clean core code, and harness code that *reads* the core verdict, do
not trip. Reuse of tools/check_core_isolation.py is verified; a missing tool or
an unparseable required file fails closed (BLOCKED).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.detectors import imports_effects
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parents[2]
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / "tools").mkdir()
    shutil.copy(
        REPO_ROOT / "tools" / "check_core_isolation.py",
        tmp_path / "tools" / "check_core_isolation.py",
    )
    return tmp_path


def _write(ws: Path, rel: str, content: str) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return rel


def _pack(*rels: str) -> DiffPack:
    files = tuple(
        ChangedFile(
            path=r,
            change_type="added",
            old_path=None,
            is_binary=False,
            added_lines=((1, 1),),
            is_untracked=False,
        )
        for r in rels
    )
    return DiffPack(base_ref="b", head_ref="WORKTREE", files=files)


def _run(ws: Path, *rels: str) -> imports_effects.DetectorResult:
    return imports_effects.run(_pack(*rels), load_policy(FAST_POLICY), ws)


def _rule_ids(result: imports_effects.DetectorResult) -> set[str]:
    return {f.rule_id for f in result.findings}


# ----- sensitivity -----------------------------------------------------------


def test_vendor_import_in_core_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/judge.py", "import openai\n\nX = 1\n")
    result = _run(ws, rel)
    assert "required.no_live_model_imports" in _rule_ids(result)


def test_effect_in_core_fails_via_reuse(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/io.py", "import os\n\np = os.getcwd()\n")
    result = _run(ws, rel)
    assert "core.no_effects" in _rule_ids(result)


def test_open_builtin_in_core_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/load.py", "def f():\n    return open('x')\n")
    result = _run(ws, rel)
    assert "core.no_effects" in _rule_ids(result)


def test_optional_lane_import_in_core_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/use.py", "from evalglass.optional.phoenix import Trace\n")
    result = _run(ws, rel)
    assert "required.no_optional_lane_imports" in _rule_ids(result)


def test_verdict_literal_in_harness_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/harness/decide.py", 'verdict = "pass"\n')
    result = _run(ws, rel)
    assert "verdict.single_engine" in _rule_ids(result)


def test_verdict_return_in_adapter_fails(ws: Path) -> None:
    rel = _write(
        ws,
        "src/evalglass/adapters/sink.py",
        'def decide_verdict():\n    return "blocked"\n',
    )
    result = _run(ws, rel)
    assert "verdict.single_engine" in _rule_ids(result)


# ----- specificity (no false positives) --------------------------------------


def test_clean_core_file_passes(ws: Path) -> None:
    rel = _write(
        ws,
        "src/evalglass/core/scores.py",
        "from __future__ import annotations\n\nfrom dataclasses import dataclass\n\n\n"
        "@dataclass\nclass Score:\n    value: float\n",
    )
    result = _run(ws, rel)
    assert result.findings == []
    assert result.blocked_reasons == []


def test_harness_reading_core_verdict_passes(ws: Path) -> None:
    rel = _write(
        ws,
        "src/evalglass/harness/report.py",
        "def render(scorecard):\n    verdict = scorecard.verdict\n    return str(verdict)\n",
    )
    result = _run(ws, rel)
    assert "verdict.single_engine" not in _rule_ids(result)


def test_verdict_module_itself_not_flagged(ws: Path) -> None:
    # The Verdict Engine is allowed to produce verdict literals.
    rel = _write(
        ws,
        "src/evalglass/core/verdict.py",
        'def decide():\n    return "pass"\n',
    )
    result = _run(ws, rel)
    assert "verdict.single_engine" not in _rule_ids(result)


def test_non_python_and_docs_ignored(ws: Path) -> None:
    rel = _write(ws, "docs/notes.md", "verdict = pass fail blocked\n")
    result = _run(ws, rel)
    assert result.findings == []
    assert result.blocked_reasons == []


# ----- fail-closed -----------------------------------------------------------


def test_missing_core_isolation_tool_blocks(tmp_path: Path) -> None:
    # No tools/check_core_isolation.py copied -> reuse impossible -> BLOCKED.
    rel = _write(tmp_path, "src/evalglass/core/x.py", "X = 1\n")
    result = imports_effects.run(_pack(rel), load_policy(FAST_POLICY), tmp_path)
    assert result.blocked_reasons


def test_unparseable_required_file_blocks(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/broken.py", "def f(:\n")
    result = _run(ws, rel)
    assert result.blocked_reasons


def test_detector_emits_ledger_entry(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/scores.py", "X = 1\n")
    result = _run(ws, rel)
    assert any(e.tool == "imports_effects" for e in result.ledger)


# ----- review hardening ------------------------------------------------------


def test_changed_isolation_helper_blocks(ws: Path) -> None:
    # If the diff also edits the helper, its scan output cannot be trusted.
    core = _write(ws, "src/evalglass/core/x.py", "import openai\n")
    helper = "tools/check_core_isolation.py"  # present in ws and now "changed"
    result = imports_effects.run(_pack(core, helper), load_policy(FAST_POLICY), ws)
    assert any("modified in this diff" in r for r in result.blocked_reasons)


def test_core_isolation_test_file_not_flagged_for_effects(ws: Path) -> None:
    # tests/core_isolation/** is required_tier for routing but may use I/O.
    rel = _write(
        ws,
        "tests/core_isolation/test_imports.py",
        "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path('.')))\n",
    )
    result = _run(ws, rel)
    assert "core.no_effects" not in _rule_ids(result)
    assert result.blocked_reasons == []


def test_relative_optional_import_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/use.py", "from ..optional.phoenix import Trace\n")
    result = _run(ws, rel)
    assert "required.no_optional_lane_imports" in _rule_ids(result)


def test_from_evalglass_import_optional_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/core/use.py", "from evalglass import optional\n")
    result = _run(ws, rel)
    assert "required.no_optional_lane_imports" in _rule_ids(result)


def test_annotated_verdict_assignment_fails(ws: Path) -> None:
    rel = _write(ws, "src/evalglass/harness/decide.py", 'verdict: str = "fail"\n')
    result = _run(ws, rel)
    assert "verdict.single_engine" in _rule_ids(result)


# ----- skills: hermetic-gate network/provider import rule ---------------------


def test_third_party_network_import_in_skill_fails(ws: Path) -> None:
    rel = _write(ws, ".claude/skills/validator-gate/scripts/fetch.py", "import requests\n")
    result = _run(ws, rel)
    assert "skills.no_network_imports" in _rule_ids(result)


def test_provider_from_import_in_skill_fails(ws: Path) -> None:
    rel = _write(ws, ".claude/skills/validator-gate/scripts/j.py", "from openai import OpenAI\n")
    result = _run(ws, rel)
    assert "skills.no_network_imports" in _rule_ids(result)


def test_stdlib_network_corner_in_skill_fails(ws: Path) -> None:
    rel = _write(ws, ".claude/skills/scan-gate/scripts/n.py", "import urllib.request\n")
    result = _run(ws, rel)
    assert "skills.no_network_imports" in _rule_ids(result)


def test_clean_skill_with_io_and_git_passes(ws: Path) -> None:
    # Gate skills legitimately read files, shell out to git, and use PyYAML/stdlib.
    rel = _write(
        ws,
        ".claude/skills/scan-gate/scripts/clean.py",
        "import json\nimport subprocess\nfrom pathlib import Path\n"
        "from urllib.parse import quote\nimport yaml\n",
    )
    result = _run(ws, rel)
    assert result.findings == []
    assert result.blocked_reasons == []


def test_skill_emitting_status_not_flagged_as_verdict(ws: Path) -> None:
    # Skills are *supposed* to emit PASS/FAIL — the verdict-engine rule must not
    # reach skill code (applies_to harness/adapters only).
    rel = _write(
        ws,
        ".claude/skills/validator-gate/scripts/compose.py",
        'def compose():\n    verdict = "fail"\n    return verdict\n',
    )
    result = _run(ws, rel)
    assert "verdict.single_engine" not in _rule_ids(result)
