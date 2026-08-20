"""Deferred-capability "declared, not exercised" guards (EG-AT4-11; alignment plan §5.10).

Every re-admitted / planned capability that does **not** ship must read honestly everywhere: it is
absent from the lane registry, its public capability status is never ``now`` (a ``now`` claim over
an absent module is the worst false-confidence case), that status is never a run *verdict*, and its
coverage row is an honest ``not_started`` + reason with no pretend scenario id.

The capability statuses are read from the HTML-derived ``CAPABILITY_REGISTRY`` (never a hand-kept
copy), anchored to the shared ``DEFERRED_CAPABILITY_KEYWORDS`` lexicon; the coverage rows are read
from the live ``eg_m5c.yaml`` registry. Test-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.core.verdict import Verdict
from evalglass.harness.lanes import built_in_lanes
from tests.egts.coverage_registry import CoverageStatus, load_registry
from tests.plugin.capability_registry import (
    CAPABILITY_REGISTRY,
    CapabilityStatus,
    build_registry,
)
from tests.plugin.lexicons import DEFERRED_CAPABILITY_KEYWORDS

pytestmark = pytest.mark.public_surface

_COVERAGE = Path(__file__).resolve().parents[1] / "egts" / "coverage" / "eg_m5c.yaml"

#: Each deferred capability: id, the HTML capability-phrase keyword, a distinctive lane-name token,
#: and its honest ``eg_m5c.yaml`` coverage row.
#:
#: *Fully deferred* (no lane registered): the token must be ABSENT from ``built_in_lanes()``.
_DEFERRED_NO_LANE = [
    ("per-source-function-view", "per-source-function", "source-function", "EG-M5C-7"),
]
#: *Registered and covered*: each connector lane IS registered (EG-R1/R2/R3) with maturity
#: ``planned`` (never ``now``), and EG-R4 has flipped EG-M5C-6 to ``covered`` with all three real
#: ``m5c.trace.*`` scenario ids. The capability is proven, yet its maturity stays ``planned`` (an
#: opt-in lane, not a GA default) — being proven is not promotion to ``now``.
_REGISTERED_COVERED = [
    ("langfuse-trace", "langfuse", "langfuse", "EG-M5C-6"),
    ("phoenix-trace", "phoenix", "phoenix", "EG-M5C-6"),
    ("langsmith-trace", "langsmith", "langsmith", "EG-M5C-6"),
]
#: Every non-``now`` capability (fully deferred + registered/covered-but-planned): each must keep a
#: roadmap status that is never ``now`` and never a run verdict.
_ALL_NON_NOW = [*_DEFERRED_NO_LANE, *_REGISTERED_COVERED]
_NO_LANE_IDS = [row[0] for row in _DEFERRED_NO_LANE]
_COVERED_IDS = [row[0] for row in _REGISTERED_COVERED]
_ALL_IDS = [row[0] for row in _ALL_NON_NOW]


def _status_for_keyword(registry: dict[str, CapabilityStatus], keyword: str) -> CapabilityStatus:
    """Resolve the capability status of the registry alias(es) containing ``keyword``.

    Fails closed if no alias matches or matching aliases disagree on status.
    """
    matched = {status for alias, status in registry.items() if keyword in alias}
    assert matched, f"no capability alias contains keyword {keyword!r}"
    assert len(matched) == 1, f"keyword {keyword!r} maps to conflicting statuses: {matched}"
    return matched.pop()


@pytest.mark.parametrize(("_id", "keyword", "_token", "_ticket"), _ALL_NON_NOW, ids=_ALL_IDS)
def test_deferred_capability_status_is_never_now(
    _id: str, keyword: str, _token: str, _ticket: str
) -> None:
    """The capability's HTML status is next/planned/experimental — never ``now`` over no module."""
    status = _status_for_keyword(CAPABILITY_REGISTRY, keyword)
    assert status is not CapabilityStatus.NOW, f"{_id} claims maturity=now while no module ships"
    assert status in {
        CapabilityStatus.NEXT,
        CapabilityStatus.PLANNED,
        CapabilityStatus.EXPERIMENTAL,
    }
    # The HTML status agrees with the shared deferred-keyword lexicon (single source of truth).
    assert DEFERRED_CAPABILITY_KEYWORDS[keyword] is status


@pytest.mark.parametrize(
    ("_id", "keyword", "token", "_ticket"), _DEFERRED_NO_LANE, ids=_NO_LANE_IDS
)
def test_deferred_capability_is_absent_from_built_in_lanes(
    _id: str, keyword: str, token: str, _ticket: str
) -> None:
    """No registered lane backs the fully-deferred capability — no required path can import it."""
    names = built_in_lanes().names()
    assert not any(token in name for name in names), f"{_id} is registered as a lane: {names}"


@pytest.mark.parametrize(("_id", "keyword", "_token", "_ticket"), _ALL_NON_NOW, ids=_ALL_IDS)
def test_deferred_capability_status_is_not_a_verdict(
    _id: str, keyword: str, _token: str, _ticket: str
) -> None:
    """A capability status string is never a run verdict (a roadmap axis, not an outcome)."""
    status = _status_for_keyword(CAPABILITY_REGISTRY, keyword)
    assert status.value not in {v.value for v in Verdict}


@pytest.mark.parametrize(
    ("_id", "_keyword", "_token", "ticket"), _DEFERRED_NO_LANE, ids=_NO_LANE_IDS
)
def test_deferred_capability_has_honest_not_exercised_row(
    _id: str, _keyword: str, _token: str, ticket: str
) -> None:
    """Each fully-deferred capability has a ``not_started`` + reason coverage row with no scenario
    id (only the per-source-function view remains here; the connectors are covered at EG-R4)."""
    registry = load_registry(_COVERAGE)
    row = next(r for r in registry.rows if r.product_ticket == ticket)
    assert row.status is CoverageStatus.NOT_STARTED
    assert row.not_exercised_reason, f"{ticket}: deferred row needs a reason"
    assert row.not_exercised_reason.strip()
    assert not row.scenario_ids


@pytest.mark.parametrize(
    ("_id", "keyword", "token", "ticket"), _REGISTERED_COVERED, ids=_COVERED_IDS
)
def test_registered_connector_lane_is_planned_and_covered(
    _id: str, keyword: str, token: str, ticket: str
) -> None:
    """A connector whose lane is registered (EG-R1/R2/R3) and proven (EG-R4 flipped EG-M5C-6) is
    honestly *covered*: the lane has maturity ``planned`` (never promoted to ``now`` by being
    proven), and its coverage row is ``covered`` with real ``m5c.trace.*`` scenario ids."""
    names = built_in_lanes().names()
    assert any(token in name for name in names), f"{_id} should be a registered lane: {names}"
    assert _status_for_keyword(CAPABILITY_REGISTRY, keyword) is CapabilityStatus.PLANNED
    row = next(r for r in load_registry(_COVERAGE).rows if r.product_ticket == ticket)
    assert row.status is CoverageStatus.COVERED, f"{ticket} is covered after EG-R4"
    assert row.scenario_ids, f"{ticket} must carry real scenario ids once covered"


def test_now_claim_over_a_deferred_capability_is_detectably_wrong() -> None:
    """Negative control: a doctored registry promoting a deferred capability to ``now`` is caught.

    Proves the ``status is not now`` guard above is not tautological — if the HTML ever marked the
    hosted-dashboard sink ``now`` while no module ships, the assertion would fail.
    """
    doctored = build_registry({CapabilityStatus.NOW: ("langfuse",)})
    status = _status_for_keyword(doctored, "langfuse")
    assert status is CapabilityStatus.NOW  # the doctored (wrong) world
    with pytest.raises(AssertionError):
        assert status is not CapabilityStatus.NOW  # the production guard fires here


def test_every_non_now_capability_is_covered_by_this_guard() -> None:
    """Completeness: the non-``now`` capabilities of plan §5.10 are all enumerated here.

    The hosted-dashboard sink + prompt-optimizer handoff left this set in EG-H2, the synthetic
    generator + annotation foundation in EG-H3, and the metrics explorer in EG-H4 (each ships its
    built surface). The remaining four are the three live trace connectors (EG-M5C-6) and the
    per-source-function view (EG-M5C-7): all three connectors are now registered + covered (EG-R1/
    R2/R3 built them, EG-R4 flipped EG-M5C-6), each staying maturity ``planned`` (never ``now``),
    and per-source-function never builds (EG-M5C-7).
    """
    assert len(_ALL_IDS) == 4
    assert len(set(_ALL_IDS)) == 4
