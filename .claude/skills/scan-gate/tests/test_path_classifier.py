"""Slice 5 (SG-P1-1): path classifier detector tests.

Sensitivity: a new unrecognized file inside the product source (src/evalglass/)
is ambiguous high-risk -> BLOCKED (it might be a new core-like module that should
face required-tier rules). Specificity: recognized locations classify cleanly and
do not block; docs/other low-risk files do not block.
"""

from __future__ import annotations

from pathlib import Path

from scripts.detectors.base import match_groups, path_matches
from scripts.detectors.path_classifier import classify, run
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"


def _pack(*paths: str) -> DiffPack:
    files = tuple(
        ChangedFile(
            path=p,
            change_type="modified",
            old_path=None,
            is_binary=False,
            added_lines=((1, 1),),
            is_untracked=False,
        )
        for p in paths
    )
    return DiffPack(base_ref="base", head_ref="HEAD", files=files)


# ----- glob matcher ----------------------------------------------------------


def test_glob_double_star_segments() -> None:
    assert path_matches("src/evalglass/core/engine.py", "src/evalglass/core/**")
    assert path_matches("src/evalglass/core/a/b.py", "src/evalglass/core/**")
    assert not path_matches("src/evalglass/harness/x.py", "src/evalglass/core/**")


def test_glob_leading_double_star() -> None:
    assert path_matches("a/b/baselines/x.json", "**/baselines/**")
    assert path_matches("baselines/x.json", "**/baselines/**")
    assert path_matches("a/x.sh", "**/*.sh")
    assert path_matches("x.sh", "**/*.sh")


def test_glob_exact_and_single_star() -> None:
    assert path_matches("pyproject.toml", "pyproject.toml")
    assert not path_matches("a/pyproject.toml", "pyproject.toml")
    assert path_matches("foo.py", "*.py")
    assert not path_matches("a/foo.py", "*.py")


# ----- classification --------------------------------------------------------


def test_classify_recognized_groups() -> None:
    policy = load_policy(FAST_POLICY)
    pack = _pack(
        "src/evalglass/core/engine.py",
        "src/evalglass/harness/cli.py",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "deploy.sh",
        "evals/baselines/main.json",
    )
    table = classify(pack, policy)
    assert "required_tier" in table["src/evalglass/core/engine.py"]
    assert "harness" in table["src/evalglass/harness/cli.py"]
    assert "ci" in table[".github/workflows/ci.yml"]
    assert "manifest" in table["pyproject.toml"]
    assert "scripts" in table["deploy.sh"]
    assert "generated_authority" in table["evals/baselines/main.json"]


def test_classify_excludes_universal_all_group() -> None:
    policy = load_policy(FAST_POLICY)
    table = classify(_pack("README.md"), policy)
    assert "all" not in table["README.md"]


# ----- detector run (sensitivity / specificity) ------------------------------


def test_specificity_recognized_product_path_does_not_block() -> None:
    policy = load_policy(FAST_POLICY)
    result = run(_pack("src/evalglass/core/engine.py"), policy)
    assert result.blocked_reasons == []


def test_sensitivity_unrecognized_product_path_blocks() -> None:
    policy = load_policy(FAST_POLICY)
    result = run(_pack("src/evalglass/mystery.py"), policy)
    assert result.blocked_reasons
    assert any("mystery.py" in r for r in result.blocked_reasons)


def test_docs_file_does_not_block() -> None:
    policy = load_policy(FAST_POLICY)
    result = run(_pack("README.md", "docs/architecture.md"), policy)
    assert result.blocked_reasons == []


def test_detector_emits_ledger_entry() -> None:
    policy = load_policy(FAST_POLICY)
    result = run(_pack("src/evalglass/core/engine.py"), policy)
    assert len(result.ledger) == 1
    assert result.ledger[0].tool == "path_classifier"
    assert result.ledger[0].network == "disabled"


def test_match_groups_includes_all_for_any_path() -> None:
    groups = match_groups("anything/here.py", {"all": ("**",), "manifest": ("pyproject.toml",)})
    assert "all" in groups


def _renamed(old: str, new: str) -> DiffPack:
    return DiffPack(
        base_ref="base",
        head_ref="HEAD",
        files=(
            ChangedFile(
                path=new,
                change_type="renamed",
                old_path=old,
                is_binary=False,
                added_lines=(),
                is_untracked=False,
            ),
        ),
    )


def test_rename_out_of_product_source_still_blocks() -> None:
    policy = load_policy(FAST_POLICY)
    result = run(_renamed("src/evalglass/mystery.py", "docs/moved.py"), policy)
    assert result.blocked_reasons
    assert any("mystery.py" in r for r in result.blocked_reasons)


def test_rename_within_core_does_not_block() -> None:
    policy = load_policy(FAST_POLICY)
    result = run(_renamed("src/evalglass/core/a.py", "src/evalglass/core/b.py"), policy)
    assert result.blocked_reasons == []


def test_rename_preserves_generated_authority_routing() -> None:
    policy = load_policy(FAST_POLICY)
    table = classify(_renamed("evals/baselines/main.json", "docs/moved.json"), policy)
    assert "generated_authority" in table["docs/moved.json"]
