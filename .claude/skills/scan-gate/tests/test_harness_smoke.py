"""Slice 0 smoke test: prove the scan-gate test harness is wired and the
skill's directory layout exists, so later slices can be built red -> green.

This test deliberately checks structure only -- there is no scanner behaviour
yet (the CLI lands in Slice 2). It gates Slice 0.
"""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def test_skill_root_is_scan_gate() -> None:
    assert SKILL_ROOT.name == "scan-gate"


def test_skill_md_exists() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()


def test_pytest_ini_exists() -> None:
    assert (SKILL_ROOT / "pytest.ini").is_file()


def test_fixture_dirs_exist() -> None:
    for sub in ("bad_diffs", "good_diffs"):
        assert (SKILL_ROOT / "tests" / "fixtures" / sub).is_dir()


def test_harness_collects_and_runs() -> None:
    # If pytest collected and ran this module, the harness is alive.
    assert True
