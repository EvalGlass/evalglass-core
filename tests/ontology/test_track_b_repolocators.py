"""Track B — repoLocator drift is now STRICT (EG-AT5-6 / EG-H1; §D 6E; ADR 0032).

Every non-null ``repoLocator`` must either resolve to a real repo path or be pinned in
``expected_repolocator_drift.json``. After the EG-H1 reconciliation the formerly-stale locators
(fake-judge / judge-collection / evaluator-protocol / calibration-record / vendored-runtime) point
at real paths, so the manifest is **empty** and every locator must resolve. The pinning mechanism
remains (an unexpected missing locator fails loudly, and any future pin must be currently
non-resolving), but there are no pinned entries today.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.ontology.ontology_loader import Ontology

pytestmark = pytest.mark.ontology

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = Path(__file__).resolve().parent / "expected_repolocator_drift.json"
_GLOB_CHARS = "*?["


def _manifest() -> dict[str, str]:
    data: dict[str, str] = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return data


def _repo_locator_resolves(locator: str) -> bool:
    """A repoLocator resolves if its file part (before ``::``) exists, or a glob has a match.

    The artifact uses ``path::symbol`` for symbol-level locators and shell globs for file sets.
    """
    file_part = locator.split("::", 1)[0]
    if any(ch in file_part for ch in _GLOB_CHARS):
        # A glob resolves only when it actually matches a file — a bare existing parent dir
        # (an empty file set) is still drift, not a resolution.
        return bool(list(_REPO_ROOT.glob(file_part)))
    return (_REPO_ROOT / file_part).exists()


def _assert_locator_resolves_or_pinned(
    entity_id: str, locator: str, manifest: dict[str, str]
) -> None:
    if _repo_locator_resolves(locator):
        return
    assert manifest.get(entity_id) == locator, (
        f"{entity_id}: repoLocator {locator!r} neither resolves nor is pinned in the drift manifest"
    )


def test_every_repolocator_resolves_or_is_pinned(real_ontology: Ontology) -> None:
    manifest = _manifest()
    for entity in real_ontology.entities:
        if entity.repo_locator:
            _assert_locator_resolves_or_pinned(entity.id, entity.repo_locator, manifest)


def test_known_stale_locators_match_manifest_exactly(real_ontology: Ontology) -> None:
    stale = {
        entity.id: entity.repo_locator
        for entity in real_ontology.entities
        if entity.repo_locator and not _repo_locator_resolves(entity.repo_locator)
    }
    assert stale == _manifest()


def test_manifest_entries_are_currently_stale(real_ontology: Ontology) -> None:
    """Each pinned entry is genuinely non-resolving — so it is removable after remediation."""
    locators = {e.id: e.repo_locator for e in real_ontology.entities}
    for entity_id, locator in _manifest().items():
        assert entity_id in locators, f"{entity_id} is pinned but absent from the ontology"
        assert not _repo_locator_resolves(locator), (
            f"{entity_id}: {locator!r} now resolves — remove it from the drift manifest"
        )


def test_resolving_locator_examples() -> None:
    """Specificity: a real source path resolves, including the ``path::symbol`` form."""
    assert _repo_locator_resolves("src/evalglass/core/verdict.py")
    assert _repo_locator_resolves("src/evalglass/core/verdict.py::VerdictPayload")
    assert _repo_locator_resolves("src/evalglass/adapters")


def test_glob_locator_requires_an_actual_match() -> None:
    """A glob whose parent dir exists but matches no file is drift, not a resolution."""
    assert not _repo_locator_resolves("src/evalglass/*.nope")  # parent exists, zero matches
    assert _repo_locator_resolves("src/evalglass/core/*.py")  # parent exists, real matches


def test_unexpected_missing_locator_fails() -> None:
    """Negative control: a bogus, unpinned locator fails the resolve-or-pinned rule."""
    assert not _repo_locator_resolves("src/evalglass/does/not/exist.py")
    with pytest.raises(AssertionError):
        _assert_locator_resolves_or_pinned("comp.brand-new", "src/evalglass/nope.py", _manifest())
