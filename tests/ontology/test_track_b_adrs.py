"""Track B — ontology ADR references resolve to real ADR files (EG-AT5-4; alignment plan §D 6D).

Every ``specifiedBy`` edge must point at an ``ADR`` entity whose id (``adr.NNNN``) resolves to
exactly one ``adrs/NNNN-*.md``; the governance concept must cite its evidence-governance ADRs; and
the in-repo drift guard introduced by this epic must have its own ADR, indexed in
``adrs/README.md``. A fabricated ``adr.9999`` reference must fail to resolve.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.ontology.ontology_loader import Ontology

pytestmark = pytest.mark.ontology

_ADRS_DIR = Path(__file__).resolve().parents[2] / "adrs"
_ADR_ID_RE = re.compile(r"^adr\.(\d{4})$")


def _adr_files(adr_entity_id: str) -> list[Path]:
    """Resolve an ``adr.NNNN`` entity id to the matching ``adrs/NNNN-*.md`` file(s)."""
    match = _ADR_ID_RE.match(adr_entity_id)
    if match is None:
        return []
    return sorted(_ADRS_DIR.glob(f"{match.group(1)}-*.md"))


def test_specifiedBy_targets_are_adr_entities(real_ontology: Ontology) -> None:
    cls = {e.id: e.cls for e in real_ontology.entities}
    edges = [r for r in real_ontology.relations if r.predicate == "specifiedBy"]
    assert edges, "the ontology models no specifiedBy edges"
    for edge in edges:
        assert cls[edge.dst] == "ADR", f"specifiedBy -> non-ADR entity {edge.dst} ({cls[edge.dst]})"


def test_every_specifiedBy_adr_resolves_to_exactly_one_file(real_ontology: Ontology) -> None:
    referenced = {r.dst for r in real_ontology.relations if r.predicate == "specifiedBy"}
    for adr_id in sorted(referenced):
        files = _adr_files(adr_id)
        assert len(files) == 1, (
            f"{adr_id} resolves to {[f.name for f in files]} (expected exactly 1)"
        )


def test_every_adr_entity_resolves_to_exactly_one_file(real_ontology: Ontology) -> None:
    for entity in real_ontology.by_class("ADR"):
        files = _adr_files(entity.id)
        assert len(files) == 1, f"{entity.id} resolves to {[f.name for f in files]}"


def test_governance_concept_cites_its_evidence_governance_adrs(real_ontology: Ontology) -> None:
    """The evidence-approval governance concept cites the generated-evidence ADRs (0021/0025)."""
    cited = {
        r.dst
        for r in real_ontology.relations
        if r.predicate == "specifiedBy" and r.src == "con.evidence-approval-governance"
    }
    assert cited == {"adr.0021", "adr.0025"}


def test_lane_adr_citations_are_pinned_as_current_drift(real_ontology: Ontology) -> None:
    """Extension/lane entities do not yet cite an ADR — recorded drift, not a silent gap.

    Post-remediation the extension lanes should cite ADR 0017 (the extension-lane framework).
    Until the site artifact adds those ``specifiedBy`` edges, the absence is pinned here; this
    assertion fires the moment a lane gains a citation, forcing a deliberate update.
    """
    extensions = {e.id for e in real_ontology.by_class("Extension")}
    assert extensions, "the ontology models no Extension entities"
    cited = {r.src for r in real_ontology.relations if r.predicate == "specifiedBy"}
    assert extensions.isdisjoint(cited), (
        "an Extension now cites an ADR — update the lane ADR expectation (target: ADR 0017)"
    )
    # The intended post-remediation target exists, so the future citation has somewhere to point.
    assert _adr_files("adr.0017"), "the extension-lane framework ADR 0017 must exist as the target"


def test_drift_guard_adr_exists_and_is_indexed() -> None:
    """The in-repo companion-ontology drift guard (this epic) has its own ADR, indexed in README."""
    matches = sorted(_ADRS_DIR.glob("*ontology-drift-guard.md"))
    assert len(matches) == 1, f"expected exactly one drift-guard ADR, found {matches}"
    adr = matches[0]
    body = adr.read_text(encoding="utf-8")
    assert "drift guard" in body.lower()
    index = (_ADRS_DIR / "README.md").read_text(encoding="utf-8")
    assert adr.name in index, "the drift-guard ADR is not indexed in adrs/README.md"


def test_fabricated_adr_id_does_not_resolve() -> None:
    """Negative control: a non-existent adr.9999 reference resolves to no file."""
    assert _adr_files("adr.9999") == []
    assert _adr_files("not-an-adr-id") == []
