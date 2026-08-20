"""FS-META-1 — the frozen-spine canary guard (EG-AT1 Slice 1, EG-AT1-1).

The v2 alignment work freezes EvalGlass's trust spine. A handful of test files
*define* that spine: the verdict matrix, authority resolution, score semantics,
aggregation, provenance, core isolation, data-policy, governance, exit mapping,
the first-run deletion proof, and the public package surface. If a later slice
silently weakens one of those tests, the spine erodes without anyone noticing.

This guard pins each spine test by the hash of its **abstract syntax** (see
:mod:`tests.egts._meta.ast_hash`). Because whitespace, blank lines, and comments
are absent from the AST, ``ruff format`` and comment churn never drift the hash;
a *semantic* change (a flipped assertion literal, an added/removed statement)
does. A drift therefore fails this guard until the committed manifest is
regenerated **in the same review** — the deliberate paired-review signal of
CLAUDE.md §23. The canary set is a closed allowlist: a manifest entry that no
longer resolves on disk, or a drift between the live set and the manifest keys,
fails loudly rather than silently dropping coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.egts._meta.ast_hash import (
    _NAMED_SPINE_FILES,
    MANIFEST_PATH,
    REPO_ROOT,
    ast_hash,
    canary_files,
    compute_canary_hashes,
    hash_file,
)

#: This guard must never appear in :data:`CANARY_FILES` — a canary that hashed
#: itself would create a self-referential loop (edit the guard, regenerate, the
#: guard now blesses its own change).
_THIS_FILE = "tests/egts/suites/test_v2_alignment_meta.py"


def _load_manifest() -> dict[str, str]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_canary_manifest_matches_live_ast() -> None:
    """Every canary's live AST hash equals the committed manifest hash."""
    live = compute_canary_hashes()
    committed = _load_manifest()
    drifted = sorted(p for p in live if live[p] != committed.get(p))
    assert not drifted, (
        "Spine test AST changed without a manifest update (FS-META-1). After "
        "deliberate review, regenerate with `python -m tests.egts._meta.ast_hash`. "
        f"Drifted: {drifted}"
    )
    assert live == committed


def test_canary_set_equals_required_spine_files() -> None:
    """The manifest key-set is exactly the full §4.0 canary set (closed allowlist)."""
    discovered = set(canary_files())
    assert set(_load_manifest()) == discovered
    # Every individually-named spine file is present...
    assert set(_NAMED_SPINE_FILES) <= discovered
    # ...and the §4.0 glob-discovered spine guards (EGTS milestone suites + the
    # public-surface snapshot tests) are actually discovered, including the
    # load-bearing ones — so a glob cannot silently match nothing.
    for required_guard in (
        "tests/egts/suites/test_m0_core_proof.py",
        "tests/egts/suites/test_m5a_deletion_proof.py",
        "tests/egts/suites/test_m5b_acceptance.py",
        "tests/public_surface/test_package_metadata.py",
        "tests/public_surface/test_scorecard_schema.py",
        "tests/public_surface/test_runrecord_schema.py",
        # The committed contract values are frozen too, not just the test logic.
        "tests/public_surface/_snapshots/scorecard_keys.json",
        "tests/public_surface/_snapshots/cli_help_surface.json",
    ):
        assert required_guard in discovered, f"§4.0 spine guard not frozen: {required_guard}"
    assert _THIS_FILE not in discovered  # a canary must never hash itself


def test_data_golden_byte_edit_drifts_hash(tmp_path: Path) -> None:
    """A data golden is byte-frozen: editing its content drifts the canary hash."""
    golden = tmp_path / "scorecard_keys.json"
    golden.write_text('{"required": ["verdict"]}\n', encoding="utf-8")
    before = hash_file(golden)
    golden.write_text('{"required": ["verdict", "sneaky"]}\n', encoding="utf-8")
    assert hash_file(golden) != before


def test_every_declared_canary_file_exists() -> None:
    """A renamed/deleted canary fails loudly instead of silently dropping coverage."""
    missing = [rel for rel in _load_manifest() if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"canary manifest references missing file(s): {missing}"


def test_sensitivity_semantic_edit_changes_hash() -> None:
    """A changed assertion literal drifts the hash — the detector fires."""
    original = "def test_x():\n    assert verdict == 'pass'\n"
    mutated = "def test_x():\n    assert verdict == 'fail'\n"
    assert ast_hash(original) != ast_hash(mutated)


def test_specificity_whitespace_reflow_keeps_hash() -> None:
    """Reformatting (blank lines, wrapping, comments) does NOT drift the hash."""
    original = "def test_x():\n    assert verdict == 'pass'\n"
    reflowed = (
        "# a freshly added comment\n"
        "def test_x():\n"
        "\n"
        "    # explain the assertion below\n"
        "    assert (\n"
        "        verdict\n"
        "        == 'pass'\n"
        "    )\n"
    )
    assert ast_hash(original) == ast_hash(reflowed)
