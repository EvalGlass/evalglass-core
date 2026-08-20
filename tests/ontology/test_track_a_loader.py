"""Track A — current-artifact loader + shape validation (EG-AT5-1; alignment plan §D 6A).

Track A validates the companion ontology **exactly as it exists today**, making no claim of
live-code equivalence (that is Track B). The micro-fixtures run always (red→green now); the
real-artifact assertions run against the vendored ``docs/design/ontology/`` copy (or an
``EVALGLASS_ONTOLOGY`` override) and **skip with a visible reason** when no artifact is present —
never a silent pass over zero entities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.ontology.ontology_loader import (
    Ontology,
    OntologyError,
    artifact_path,
    load_ontology,
    load_real_ontology,
    parse_ontology,
)

pytestmark = pytest.mark.ontology

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _base() -> dict[str, Any]:
    """A structurally valid ontology dict (good_minimal) to mutate in fail-closed tests."""
    data: dict[str, Any] = json.loads(
        (_FIXTURES / "good_minimal" / "evalglass-ontology.json").read_text(encoding="utf-8")
    )
    return data


def _real_or_skip() -> Ontology:
    ontology = load_real_ontology()
    if ontology is None:
        pytest.skip(
            "NOT EXERCISED — no ontology artifact at EVALGLASS_ONTOLOGY or the in-repo copy"
        )
    return ontology


# --- micro-fixtures (always run) --------------------------------------------
def test_loader_accepts_minimal_valid() -> None:
    ontology = load_ontology(_FIXTURES / "good_minimal" / "evalglass-ontology.json")
    assert len(ontology.entities) == 2
    assert len(ontology.relations) == 1
    assert ontology.entity_ids() == {"layer.core", "enum.verdict"}


def test_loader_rejects_empty_entity_id() -> None:
    with pytest.raises(OntologyError):
        load_ontology(_FIXTURES / "bad_empty_entity" / "evalglass-ontology.json")


def test_loader_rejects_non_json(tmp_path: Path) -> None:
    (tmp_path / "o.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(OntologyError):
        load_ontology(tmp_path / "o.json")


def test_loader_rejects_missing_top_level_key(tmp_path: Path) -> None:
    (tmp_path / "o.json").write_text('{"ontology": "evalglass"}', encoding="utf-8")
    with pytest.raises(OntologyError):
        load_ontology(tmp_path / "o.json")


def test_loader_rejects_non_slash_evidence_locator() -> None:
    data = _base()
    data["entities"][0]["evidence"] = ["docs/no-leading-slash"]
    with pytest.raises(OntologyError):
        parse_ontology(data)


def test_loader_rejects_unknown_predicate() -> None:
    data = _base()
    data["relations"][0]["predicate"] = "totallyMadeUp"
    with pytest.raises(OntologyError):
        parse_ontology(data)


def test_loader_rejects_dangling_relation_endpoint() -> None:
    data = _base()
    data["relations"][0]["to"] = "layer.does-not-exist"
    with pytest.raises(OntologyError):
        parse_ontology(data)


# --- real artifact (skip-with-count when unavailable) -----------------------
def test_real_artifact_loads_when_present() -> None:
    ontology = _real_or_skip()
    assert ontology.entities, "the artifact must enumerate entities"
    assert ontology.relations, "the artifact must enumerate relations"


def test_real_artifact_stats_match_lengths() -> None:
    ontology = _real_or_skip()
    assert ontology.stats["entities"] == len(ontology.entities)
    assert ontology.stats["relations"] == len(ontology.relations)


def test_real_artifact_entity_ids_are_unique() -> None:
    ontology = _real_or_skip()
    assert len(ontology.entity_ids()) == len(ontology.entities)


def test_real_artifact_meta_classes_is_a_dict_of_fifteen() -> None:
    ontology = _real_or_skip()
    classes = ontology.meta["classes"]
    assert isinstance(classes, dict)
    assert len(classes) == 15


def test_real_artifact_byclass_counts_match_entities() -> None:
    ontology = _real_or_skip()
    counted: dict[str, int] = {}
    for entity in ontology.entities:
        counted[entity.cls] = counted.get(entity.cls, 0) + 1
    assert dict(ontology.stats["byClass"]) == counted


def test_artifact_path_points_at_the_in_repo_copy_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Clear any override so this asserts the *default* (vendored) path, not an env-supplied one.
    monkeypatch.delenv("EVALGLASS_ONTOLOGY", raising=False)
    path = artifact_path()
    if path is None:
        pytest.skip("NOT EXERCISED — no in-repo ontology artifact available")
    assert path.is_file()
    assert path.name == "evalglass-ontology.json"
