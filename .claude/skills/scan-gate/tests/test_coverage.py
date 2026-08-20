"""Coverage report: a PASS over universal-only changes must be flagged as not-a-trust-check."""

from __future__ import annotations

from pathlib import Path

from scripts.coverage import (
    build_coverage,
    coverage_counts,
    coverage_note,
    render_debug,
    summary_line,
)
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import Policy, load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


def _pack(*paths: str) -> DiffPack:
    files = tuple(
        ChangedFile(
            path=p,
            change_type="added",
            old_path=None,
            is_binary=False,
            added_lines=((1, 1),),
            is_untracked=False,
        )
        for p in paths
    )
    return DiffPack(base_ref="base", head_ref="head", files=files)


def _policy() -> Policy:
    return load_policy(_POLICY)


def test_skill_python_is_trust_scoped():
    # Skill Python now matches the `skills` group (skills.no_network_imports),
    # so it is genuinely trust-checked — not an anonymous `all`-only fall-through.
    policy = _policy()
    pack = _pack(
        ".claude/skills/validator-gate/scripts/router.py",
        ".claude/skills/validator-gate/tests/test_router.py",
    )
    report = build_coverage(pack, policy, "fast")
    assert not report.has_blind_spot
    assert summary_line(report) is None
    for fc in report.files:
        assert fc.trust_scoped is True
        assert fc.groups == ("all", "skills")
        assert "imports_effects" in fc.detectors


def test_non_code_paths_remain_a_blind_spot():
    # Docs / non-Python changes still match only the universal group: a PASS over
    # them is honestly flagged as not-a-trust-check.
    policy = _policy()
    pack = _pack("docs/architecture.md", "notes/scratch.txt")
    report = build_coverage(pack, policy, "fast")
    assert report.has_blind_spot
    assert len(report.universal_only) == 2
    for fc in report.files:
        assert fc.trust_scoped is False
        assert fc.groups == ("all",)
        assert fc.detectors == ("secrets",)
    note = summary_line(report)
    assert note is not None
    assert "NOT a trust check" in note


def test_product_paths_are_trust_scoped():
    policy = _policy()
    pack = _pack("src/evalglass/core/verdict.py", "src/evalglass/harness/cli.py")
    report = build_coverage(pack, policy, "fast")
    assert not report.has_blind_spot
    assert summary_line(report) is None
    for fc in report.files:
        assert fc.trust_scoped is True
        assert "imports_effects" in fc.detectors


def test_mixed_diff_reports_only_uncovered():
    policy = _policy()
    pack = _pack("src/evalglass/core/verdict.py", "docs/architecture.md")
    report = build_coverage(pack, policy, "fast")
    assert report.has_blind_spot
    uncovered = [f.path for f in report.universal_only]
    assert uncovered == ["docs/architecture.md"]
    table = render_debug(report)
    assert "architecture.md" in table
    assert "verdict.py" in table


def test_coverage_counts_for_json():
    policy = _policy()
    pack = _pack(
        "src/evalglass/core/verdict.py",  # trust-scoped
        "docs/architecture.md",  # universal-only
        "notes/scratch.txt",  # universal-only
    )
    report = build_coverage(pack, policy, "fast")
    counts = coverage_counts(report)
    assert counts == {"trust_scoped": 1, "not_trust_scoped": 2}


def test_coverage_note_names_untrusted_files():
    policy = _policy()
    pack = _pack("src/evalglass/core/verdict.py", "docs/architecture.md")
    report = build_coverage(pack, policy, "fast")
    note = coverage_note(report)
    assert note is not None
    assert "docs/architecture.md" in note
    assert "verdict.py" not in note  # trust-scoped files are not named as gaps


def test_coverage_note_none_when_all_trust_scoped():
    policy = _policy()
    pack = _pack("src/evalglass/core/verdict.py", ".claude/skills/x/scripts/a.py")
    report = build_coverage(pack, policy, "fast")
    assert coverage_note(report) is None
    assert coverage_counts(report) == {"trust_scoped": 2, "not_trust_scoped": 0}
