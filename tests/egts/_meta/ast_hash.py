"""AST-scoped canary hashing for the frozen-spine meta guard (EG-AT1-1, FS-META-1).

The hash is a function of a file's *abstract syntax* — its statement structure,
identifiers, and literal values — not its bytes. Whitespace, blank lines, and
comments do not appear in the AST, so reformatting (``ruff format``) and comment
churn never drift the hash; a semantic edit (a changed assertion literal, an
added or removed statement) does. The serialization deliberately skips the
version-variable ``type_params`` / ``type_comment`` fields so the same source
hashes identically across the Python 3.12 and 3.13 CI matrix. Whole-file byte
hashing is *rejected* on purpose: it false-fails on formatting and trains
reviewers to rubber-stamp manifest churn (CLAUDE.md §21 Lesson 1).

Regenerate the committed manifest after a deliberately reviewed spine change::

    python -m tests.egts._meta.ast_hash
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

#: Repository root: this file is ``<root>/tests/egts/_meta/ast_hash.py``.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The committed ``{relative-path: ast-hash}`` manifest.
MANIFEST_PATH = Path(__file__).resolve().parent / "canary_ast_hashes.json"

#: Spine-defining tests named *individually* in the frozen-spine plan (§4.0).
#: Adding one here is deliberate — the manifest diff is the paired-review signal.
#: This module's own guard is intentionally absent: a canary must never hash
#: itself. The EGTS milestone suites below are discovered by pattern, not listed.
_NAMED_SPINE_FILES: tuple[str, ...] = (
    "tests/core/test_verdict.py",
    "tests/core/test_authority.py",
    "tests/core/test_scores.py",
    "tests/core/test_aggregation.py",
    "tests/core/test_provenance.py",
    "tests/core_isolation/test_core_imports.py",
    "tests/core_isolation/test_installer_boundary.py",
    "tests/core_isolation/test_judge_live_boundary.py",
    "tests/core_isolation/test_lane_boundary.py",
    "tests/core_isolation/test_lane_v2_boundary.py",
    "tests/core_isolation/test_v2_trust_invariants.py",
    "tests/harness/test_data_policy.py",
    "tests/harness/test_governance.py",
    "tests/harness/test_exits.py",
    "tests/harness/test_lane_attach.py",
    "tests/plugin/test_first_run_e2e.py",
    "tests/plugin/test_crossruntime_independence.py",
    "tests/plugin/test_honesty_audit.py",
    # The test-only capability-status taxonomy the FS-SNAP-6 disjointness proof
    # rests on: freezing it means a silent edit to the enum drifts the hash, not
    # only the (already byte-frozen) enum_members.json golden.
    "tests/plugin/status_registry.py",
    # The shared checker logic the public-surface guards depend on (not a test_*.py
    # file, so it is named rather than discovered) — neutering it would let a
    # FS-SNAP guard pass while checking nothing.
    "tests/public_surface/_normalize.py",
    # FS-EGTS: the v2 coverage-superset guard and its frozen floor (byte-hashed),
    # so the proof floor cannot be silently lowered.
    "tests/egts/test_v2_targets_superset.py",
    "tests/egts/_snapshots/egts_targets.json",
)

#: Spine test *directories* whose ``test_*.py`` files are all canaries, discovered
#: by glob (§4.0 names them as patterns, not individually). A newly added guard —
#: an EGTS milestone suite or a public-surface FS-SNAP test — therefore auto-joins
#: the freeze and forces a loud manifest update; it cannot silently escape it.
_GLOB_SPINE_DIRS: dict[str, tuple[str, ...]] = {
    # §4.0: "test_m0..m5b_*_proof.py + test_mX_acceptance.py".
    "tests/egts/suites": ("test_m*_proof.py", "test_m*_acceptance.py"),
    # §4.0: the public-surface snapshot tests (test_package_metadata + FS-SNAP-*).
    "tests/public_surface": ("test_*.py",),
    # The committed public-surface contract values themselves (byte-frozen via
    # hash_file), so a golden cannot be edited to bless a drifted product silently.
    "tests/public_surface/_snapshots": ("*.json", "*.txt"),
}


def _discover_glob_spine(repo_root: Path) -> tuple[str, ...]:
    found = {
        path.relative_to(repo_root).as_posix()
        for rel_dir, patterns in _GLOB_SPINE_DIRS.items()
        for pattern in patterns
        for path in (repo_root / rel_dir).glob(pattern)
    }
    return tuple(sorted(found))


def canary_files(repo_root: Path = REPO_ROOT) -> tuple[str, ...]:
    """Return the full §4.0 canary set: named spine files + discovered spine suites."""
    return tuple(sorted({*_NAMED_SPINE_FILES, *_discover_glob_spine(repo_root)}))


#: AST fields excluded from the serialization: ``type_params`` (PEP 695) and
#: ``type_comment`` vary by Python version / carry no behavioral weight for these
#: tests, so skipping them keeps the hash stable across the 3.12/3.13 matrix.
_SKIP_FIELDS = frozenset({"type_comment", "type_params"})


def _serialize(node: object) -> str:
    """Canonically serialize an AST node, position- and version-independently."""
    if isinstance(node, ast.AST):
        parts = [type(node).__name__]
        for field, value in ast.iter_fields(node):
            if field in _SKIP_FIELDS:
                continue
            parts.append(f"{field}={_serialize(value)}")
        return "(" + ",".join(parts) + ")"
    if isinstance(node, list):
        return "[" + ",".join(_serialize(item) for item in node) + "]"
    return repr(node)


def ast_hash(source: str) -> str:
    """Return the version-stable SHA-256 AST hash of Python ``source``."""
    serialized = _serialize(ast.parse(source))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    """Hash a canary file: AST hash for Python, byte hash for data goldens.

    Python files are hashed by abstract syntax (format-insensitive). Data goldens
    under ``_snapshots/`` — the committed *contract values* (JSON keysets, the CLI
    surface, CI/report shapes) — are byte-frozen, so editing a golden to match a
    drifted product still drifts the manifest: the loud paired-review signal that a
    public-surface contract changed (CLAUDE.md §23). Their content carries no
    Python AST to hash, and ``ruff`` never reformats them, so a raw byte hash is
    exact without false-failing.
    """
    if path.suffix == ".py":
        return ast_hash(path.read_text(encoding="utf-8"))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_canary_hashes(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Compute the ``{relative-path: ast-hash}`` map over every canary file."""
    return {rel: hash_file(repo_root / rel) for rel in canary_files(repo_root)}


def _write_manifest() -> None:
    manifest = compute_canary_hashes()
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    _write_manifest()
    print(f"wrote {MANIFEST_PATH} ({len(canary_files())} canaries)")
