"""Shared fixtures for the ontology drift-guard suite (EG-AT5)."""

from __future__ import annotations

import pytest

from tests.ontology.ontology_loader import Ontology, load_real_ontology


@pytest.fixture
def real_ontology() -> Ontology:
    """The real companion ontology, or a visible skip when no artifact is available.

    Skip-with-count, never a silent pass over zero entities (alignment plan §3.1, GAP P1-2).
    """
    ontology = load_real_ontology()
    if ontology is None:
        pytest.skip(
            "NOT EXERCISED — no ontology artifact at EVALGLASS_ONTOLOGY or the in-repo copy"
        )
    return ontology
