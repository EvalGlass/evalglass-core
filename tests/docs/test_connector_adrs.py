"""Live trace-connector ADRs exist, are accepted, and are indexed (EG-R0-1).

EG-R0 opens the live-connector boundary the hermetic tranche deliberately deferred
(``docs/M6_TICKET_CORRECTIONS.md`` C1/C2). Before any provider SDK or adapter lands
(EG-R0-2 … EG-R3), each connector must be an **explicit architectural decision**: one
cross-cutting boundary ADR plus one ADR per provider, each naming the selected package,
the optional extra key, the lazy lane-local import boundary, the credential model, the
deletion rule, and the ``live_lane`` test policy.

This guard also pins two durable, repo-wide invariants that hold today: every
``adrs/NNNN-*.md`` file is linked in ``adrs/README.md``, and every README link resolves to
a real file. A new ADR that forgets its index entry — or a stale link — fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ADRS = _ROOT / "adrs"
_README = _ADRS / "README.md"

#: The cross-cutting connector boundary ADR and the three per-provider ADRs (EG-R0-1).
_CONNECTOR_BOUNDARY_ADR = "0033"
_PROVIDER_ADRS = {"0034": "langfuse", "0035": "phoenix", "0036": "langsmith"}

#: Decision points every provider ADR must record (acceptance criteria, EG-R0-1).
_PROVIDER_DECISION_TOKENS = ("extra", "lazy", "credential", "deletion", "live_lane", "optional")


def _adr_file(number: str) -> Path:
    matches = sorted(_ADRS.glob(f"{number}-*.md"))
    assert len(matches) == 1, f"ADR {number} resolves to {[m.name for m in matches]} (expected 1)"
    return matches[0]


def test_every_adr_file_is_indexed_in_readme() -> None:
    index = _README.read_text(encoding="utf-8")
    for adr in sorted(_ADRS.glob("0*.md")):
        assert adr.name in index, f"ADR file not linked in adrs/README.md: {adr.name}"


def test_every_readme_adr_link_resolves() -> None:
    index = _README.read_text(encoding="utf-8")
    targets = re.findall(r"\]\((\d{4}-[a-z0-9-]+\.md)\)", index)
    assert targets, "adrs/README.md indexes no ADR links"
    for target in targets:
        assert (_ADRS / target).is_file(), f"adrs/README.md links a missing file: {target}"


def test_connector_boundary_adr_exists_and_is_accepted() -> None:
    text = _adr_file(_CONNECTOR_BOUNDARY_ADR).read_text(encoding="utf-8")
    assert "**Status:** accepted" in text, "connector boundary ADR is not accepted"
    low = text.lower()
    # The boundary states optionality, lazy lane-local import, credentials, deletion, the
    # live_lane policy, and the evidence-not-authority rule.
    for token in (
        "optional",
        "lazy",
        "live_lane",
        "deletion",
        "credential",
        "evidence",
        "authority",
    ):
        assert token in low, f"connector boundary ADR omits {token!r}"


@pytest.mark.parametrize(("number", "provider"), sorted(_PROVIDER_ADRS.items()))
def test_provider_adr_declares_its_decision_points(number: str, provider: str) -> None:
    text = _adr_file(number).read_text(encoding="utf-8")
    assert "**Status:** accepted" in text, f"provider ADR {number} is not accepted"
    low = text.lower()
    assert provider in low, f"ADR {number} does not name provider {provider!r}"
    for token in _PROVIDER_DECISION_TOKENS:
        assert token in low, f"provider ADR {number} ({provider}) omits decision point {token!r}"
    assert _CONNECTOR_BOUNDARY_ADR in text, (
        f"provider ADR {number} should cite the connector boundary ADR {_CONNECTOR_BOUNDARY_ADR}"
    )
