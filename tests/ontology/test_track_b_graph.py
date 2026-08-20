"""Track B — graph well-formedness, predicates, ports, lane-authority edges (EG-AT5-5; §D 6E).

The ontology graph must reflect EvalGlass's real port/lane boundaries: the verified 15 predicates
(including ``exposes``, which the HTML map's list omitted); every ``Port`` is implemented by an
adapter Component; every extension lane ``attachesVia`` a real ``Port``; and **no** lane
``produces`` *or* ``implements`` an authority contract (``Score`` / ``VerdictPayload`` /
``ResolvedAuthority``). The ``bad_lane_grants_authority`` fixture proves the check fires.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.ontology.ontology_loader import Ontology, load_ontology, parse_ontology

pytestmark = pytest.mark.ontology

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The verified predicate vocabulary (Appendix B) — note ``exposes`` is real.
_PREDICATES = frozenset(
    {
        "attachesVia",
        "consumes",
        "dependsOn",
        "enforces",
        "exposes",
        "governs",
        "hasValue",
        "implements",
        "invokes",
        "partOf",
        "performedBy",
        "precedes",
        "produces",
        "specifiedBy",
        "typedBy",
    }
)

#: Contracts a lane may never emit — they belong to the scoring/authority/verdict path.
_AUTHORITY_CONTRACTS = frozenset({"ctr.score", "ctr.verdict-payload", "ctr.resolved-authority"})
#: Edges that would launder authority if they ran from a lane to an authority contract.
_AUTHORITY_GRANTING_PREDICATES = ("produces", "implements")
#: Tokens identifying an adapter Component (the only legitimate ``implements`` source for a Port).
_ADAPTER_TOKENS = ("adapter", "connector", "sink")

#: Extensions that are views/UIs, not port-attached lanes — pinned so a new lane can't skip a port.
_NON_PORT_EXTENSIONS = frozenset(
    {"ext.metrics-explorer", "ext.annotation-ui", "ext.visual-baseline-view"}
)


def _assert_no_extension_grants_authority(ontology: Ontology) -> None:
    """A lane may neither ``produces`` nor ``implements`` an authority contract (§6E)."""
    extensions = {e.id for e in ontology.by_class("Extension")}
    offenders = [
        (r.predicate, r.src, r.dst)
        for r in ontology.relations
        if r.predicate in _AUTHORITY_GRANTING_PREDICATES
        and r.src in extensions
        and r.dst in _AUTHORITY_CONTRACTS
    ]
    assert offenders == [], f"a lane/extension grants authority: {offenders}"


# --- real artifact (skip-with-count when unavailable) -----------------------
def test_no_dangling_relation_endpoints(real_ontology: Ontology) -> None:
    ids = real_ontology.entity_ids()
    dangling = [
        (r.predicate, r.src, r.dst)
        for r in real_ontology.relations
        if r.src not in ids or r.dst not in ids
    ]
    assert dangling == []


def test_predicate_set_is_the_verified_fifteen(real_ontology: Ontology) -> None:
    used = {r.predicate for r in real_ontology.relations}
    assert used == _PREDICATES
    assert set(real_ontology.meta["predicates"].keys()) == _PREDICATES
    assert "exposes" in used  # real, though the HTML map's predicate list omitted it


def test_every_port_is_implemented_by_an_adapter_component(real_ontology: Ontology) -> None:
    cls = {e.id: e.cls for e in real_ontology.entities}
    ports = {e.id for e in real_ontology.by_class("Port")}
    implemented: set[str] = set()
    for rel in real_ontology.relations:
        if rel.predicate != "implements":
            continue
        assert cls[rel.src] == "Component", f"implements from a non-Component: {rel.src}"
        assert any(tok in rel.src for tok in _ADAPTER_TOKENS), (
            f"implements from a non-adapter component: {rel.src}"
        )
        implemented.add(rel.dst)
    assert ports <= implemented, (
        f"ports with no adapter implements edge: {sorted(ports - implemented)}"
    )


def test_every_attachesVia_targets_a_real_port(real_ontology: Ontology) -> None:
    ports = {e.id for e in real_ontology.by_class("Port")}
    extensions = {e.id for e in real_ontology.by_class("Extension")}
    attaching = set()
    for rel in real_ontology.relations:
        if rel.predicate == "attachesVia":
            assert rel.src in extensions, f"attachesVia from a non-Extension: {rel.src}"
            assert rel.dst in ports, f"attachesVia to a non-Port: {rel.dst}"
            attaching.add(rel.src)
    # Every extension is either a port-attached lane or a known (pinned) view/UI.
    assert extensions - attaching == _NON_PORT_EXTENSIONS


def test_no_lane_grants_authority(real_ontology: Ontology) -> None:
    _assert_no_extension_grants_authority(real_ontology)


# --- negative control fixture -----------------------------------------------
_BAD_FIXTURE = _FIXTURES / "bad_lane_grants_authority" / "evalglass-ontology.json"


def test_bad_lane_produces_authority_fixture_fails() -> None:
    with pytest.raises(AssertionError):
        _assert_no_extension_grants_authority(load_ontology(_BAD_FIXTURE))


def test_lane_implements_authority_contract_also_fails() -> None:
    """The check covers implements-laundering too, not only produces."""
    data = json.loads(_BAD_FIXTURE.read_text(encoding="utf-8"))
    data["relations"][1]["predicate"] = "implements"  # implements -> VerdictPayload
    with pytest.raises(AssertionError):
        _assert_no_extension_grants_authority(parse_ontology(data))
