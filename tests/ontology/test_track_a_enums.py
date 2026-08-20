"""Track A — current enum entities are internally consistent (EG-AT5-2; alignment plan §D 6B).

After the EG-H1 reconciliation the artifact models 14 ``Enum`` entities whose members are 55
``EnumValue`` entities, connected by ``hasValue`` edges. This slice validates that internal
structure **without** comparing to the live Python enums — that comparison is Track B (EG-AT5-3).
The negative controls confirm a dangling or mis-typed ``hasValue`` endpoint is rejected.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.ontology.ontology_loader import Ontology, OntologyError, parse_ontology

pytestmark = pytest.mark.ontology

_ENUM = "Enum"
_ENUM_VALUE = "EnumValue"
_HAS_VALUE = "hasValue"


def _class_by_id(ontology: Ontology) -> dict[str, str]:
    return {entity.id: entity.cls for entity in ontology.entities}


def _assert_hasValue_links_enum_to_value(ontology: Ontology) -> None:
    """Every ``hasValue`` edge runs Enum -> EnumValue (the check exercised by the negatives)."""
    cls = _class_by_id(ontology)
    edges = [r for r in ontology.relations if r.predicate == _HAS_VALUE]
    assert edges, "the ontology models no hasValue edges"
    for edge in edges:
        assert cls[edge.src] == _ENUM, f"hasValue from a non-Enum: {edge.src} ({cls[edge.src]})"
        assert cls[edge.dst] == _ENUM_VALUE, f"hasValue to a non-EnumValue: {edge.dst}"


def _enum_ontology() -> dict[str, Any]:
    """A minimal self-contained ontology: one Enum with two EnumValues via hasValue."""
    return {
        "ontology": "evalglass",
        "version": "t",
        "generated": "g",
        "about": "A minimal enum ontology for internal-consistency tests.",
        "meta": {
            "classes": {
                "Enum": {"prefix": "enum", "desc": "A closed vocabulary."},
                "EnumValue": {"prefix": "enumval", "desc": "A member."},
                "Layer": {"prefix": "layer", "desc": "A layer."},
            },
            "predicates": {
                "hasValue": {"domain": ["Enum"], "range": ["EnumValue"], "desc": "owns"}
            },
            "status": ["now", "next", "planned", "experimental"],
            "verification": ["asserted", "conceptual"],
            "idScheme": "prefix.suffix",
        },
        "stats": {"entities": 3, "relations": 2, "byClass": {"Enum": 1, "EnumValue": 2}},
        "entities": [
            _entity("enum.verdict", "Enum", "Verdict"),
            _entity("enumval.verdict-pass", "EnumValue", "pass"),
            _entity("enumval.verdict-fail", "EnumValue", "fail"),
        ],
        "relations": [
            {"predicate": "hasValue", "from": "enum.verdict", "to": "enumval.verdict-pass"},
            {"predicate": "hasValue", "from": "enum.verdict", "to": "enumval.verdict-fail"},
        ],
    }


def _entity(ident: str, cls: str, label: str) -> dict[str, Any]:
    return {
        "id": ident,
        "class": cls,
        "kind": None,
        "label": label,
        "definition": f"the {label} entity",
        "status": "now",
        "verification": "asserted",
        "repoLocator": None,
        "evidence": ["/docs/reference/enums"],
        "notes": None,
    }


# --- real artifact (skip-with-count when unavailable) -----------------------
def test_fourteen_enum_entities(real_ontology: Ontology) -> None:
    assert len(real_ontology.by_class(_ENUM)) == 14


def test_fifty_five_enum_value_entities(real_ontology: Ontology) -> None:
    assert len(real_ontology.by_class(_ENUM_VALUE)) == 55


def test_every_hasValue_links_enum_to_enum_value(real_ontology: Ontology) -> None:
    _assert_hasValue_links_enum_to_value(real_ontology)


def test_every_enum_value_is_owned_by_an_enum(real_ontology: Ontology) -> None:
    owned = {r.dst for r in real_ontology.relations if r.predicate == _HAS_VALUE}
    values = {e.id for e in real_ontology.by_class(_ENUM_VALUE)}
    assert values <= owned, f"orphan EnumValue entities: {sorted(values - owned)}"


def test_every_enum_has_at_least_one_value(real_ontology: Ontology) -> None:
    sources = {r.src for r in real_ontology.relations if r.predicate == _HAS_VALUE}
    enums = {e.id for e in real_ontology.by_class(_ENUM)}
    assert enums <= sources, f"Enum entities with no members: {sorted(enums - sources)}"


# --- self-contained internal-consistency + negatives (always run) -----------
def test_minimal_enum_ontology_is_internally_consistent() -> None:
    _assert_hasValue_links_enum_to_value(parse_ontology(_enum_ontology()))


def test_dangling_hasValue_endpoint_is_rejected_by_loader() -> None:
    data = _enum_ontology()
    data["relations"][0]["to"] = "enumval.does-not-exist"
    with pytest.raises(OntologyError):
        parse_ontology(data)


def test_hasValue_to_a_non_enum_value_is_caught() -> None:
    data = _enum_ontology()
    # Point a hasValue at an existing but wrong-class entity (a Layer), not an EnumValue.
    data["entities"].append(_entity("layer.core", "Layer", "Core"))
    data["relations"][0]["to"] = "layer.core"
    with pytest.raises(AssertionError):
        _assert_hasValue_links_enum_to_value(parse_ontology(data))
