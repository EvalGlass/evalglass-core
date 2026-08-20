"""EG-AT3-3 — cross-surface capability-status consistency (alignment plan §7.1, ST-CONSIST).

The architecture map is the single source of capability status. These guards prove
the committed registry agrees with the live HTML, that no deferred capability is shown
as shipped-now (ST-CONSIST-2) or without an honest future marker (ST-CONSIST-3) on any
real user-facing prose surface, and that ``src/`` never imports the test-only status
taxonomy (ST-CONSIST-4).

Both prose scans operate at **sentence granularity over joined logical blocks**: lines
are joined so a qualifier on a bullet's wrapped continuation line still counts, then split
into sentences so one qualified sentence cannot bless an unrelated bare mention in the same
bullet.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.plugin.capability_registry import (
    ARCH_HTML,
    CAPABILITY_REGISTRY,
    CAPABILITY_STATUSES,
    parse_capability_statuses,
)
from tests.plugin.lexicons import (
    DEFERRED_CAPABILITY_KEYWORDS,
    NEGATORS,
    NOW_MARKERS,
    has_future_marker,
)
from tests.plugin.prose_scan import scan_capability_sentences as _scan
from tests.plugin.rendered_surfaces import audited_prose_files as _audited_surfaces
from tests.plugin.status_registry import CapabilityStatus

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = Path(__file__).parent / "fixtures"
_SRC = _REPO / "src" / "evalglass"

#: Genuinely-unshipped capability families that ST-CONSIST must be able to *see* in prose. Release
#: / process aliases the map also marks non-``now`` (e.g. "0.1 tagged release", "pypi publishing",
#: "more worked examples") are not user-facing runnable capabilities and are out of scope here.
_REQUIRED_FAMILIES = frozenset(
    {
        "dashboard",
        "optimizer",
        "langfuse",
        "phoenix",
        "langsmith",
        "synthetic",
        "annotation",
        "metrics explorer",
        "per-source-function",
    }
)


def _asserts_now(sentence: str) -> bool:
    """True if the sentence claims a capability ships *now*, unless that claim is negated.

    Only a negation immediately before the now-phrase ("not available now") suppresses the
    claim — a future marker about a *different* capability elsewhere in the sentence does not.
    """
    lowered = sentence.lower()
    for marker in NOW_MARKERS:
        idx = lowered.find(marker)
        if idx == -1:
            continue
        prefix = lowered[max(0, idx - 24) : idx]
        if any(negator in prefix for negator in NEGATORS):
            continue
        return True
    return False


# --------------------------------------------------------------------------- ST-CONSIST-1


@pytest.mark.public_surface
def test_committed_registry_agrees_with_live_html() -> None:
    parsed = parse_capability_statuses(ARCH_HTML.read_text(encoding="utf-8"))
    assert set(parsed) == set(CapabilityStatus)
    assert parsed == CAPABILITY_STATUSES  # import-time registry == a fresh parse


@pytest.mark.public_surface
def test_deferred_keywords_are_anchored_to_the_registry() -> None:
    """Every deferred keyword maps to a non-``now`` capability the architecture map declares."""
    for keyword, status in DEFERRED_CAPABILITY_KEYWORDS.items():
        matches = [s for alias, s in CAPABILITY_REGISTRY.items() if keyword in alias]
        assert matches, f"deferred keyword {keyword!r} is in no registry alias"
        assert all(s is status for s in matches), f"{keyword!r} status disagrees with the registry"
        assert status is not CapabilityStatus.NOW


@pytest.mark.public_surface
def test_every_unshipped_capability_family_has_a_scan_keyword() -> None:
    """Reverse coverage: each genuinely-unshipped family is visible to the prose scans."""
    covered = " ".join(DEFERRED_CAPABILITY_KEYWORDS)
    missing = [family for family in _REQUIRED_FAMILIES if family not in covered]
    assert missing == [], f"unshipped families with no scan keyword: {missing}"


# --------------------------------------------------------------------------- ST-CONSIST-2


@pytest.mark.public_surface
def test_no_deferred_capability_is_shown_shipped_now() -> None:
    assert _scan(_audited_surfaces(), _asserts_now) == []


@pytest.mark.public_surface
def test_consist2_sensitivity_dashboard_now_conflict_fires() -> None:
    assert _scan([_FIXTURES / "conflict_dashboard_now.md"], _asserts_now) != []


@pytest.mark.public_surface
def test_now_claim_is_not_suppressed_by_a_future_marker_about_another_capability() -> None:
    # A future marker about a *different* capability must not bless an explicit now-claim.
    assert _asserts_now(
        "synthetic-data generation is planned, but the dashboard sink is available now"
    )
    # ...while an actual negation of the now-phrase does suppress it.
    assert not _asserts_now("the hosted dashboard sink is not available now")


# --------------------------------------------------------------------------- ST-CONSIST-3


@pytest.mark.public_surface
def test_every_deferred_capability_carries_a_future_marker() -> None:
    assert _scan(_audited_surfaces(), lambda sentence: not has_future_marker(sentence)) == []


@pytest.mark.public_surface
def test_consist3_sensitivity_bare_mention_fires() -> None:
    assert (
        _scan([_FIXTURES / "bare_synth.md"], lambda sentence: not has_future_marker(sentence)) != []
    )


@pytest.mark.public_surface
def test_consist3_specificity_qualified_mention_stays_quiet() -> None:
    good = [_FIXTURES / "good_future.md"]
    assert _scan(good, lambda sentence: not has_future_marker(sentence)) == []
    assert _scan(good, _asserts_now) == []


# --------------------------------------------------------------------------- ST-CONSIST-4


def _status_import_offenders(source: str, name: str) -> list[str]:
    offenders: list[str] = []
    tree = ast.parse(source, filename=name)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tests."):
            offenders.append(f"{name}: from {node.module}")
        if isinstance(node, ast.Import):
            offenders += [
                f"{name}: import {a.name}" for a in node.names if a.name.startswith("tests.")
            ]
    if "CapabilityStatus" in source:
        offenders.append(f"{name}: references CapabilityStatus")
    return offenders


@pytest.mark.core_isolation
def test_src_imports_no_status_registry_or_token() -> None:
    offenders: list[str] = []
    for py in _SRC.rglob("*.py"):
        offenders += _status_import_offenders(py.read_text(encoding="utf-8"), py.name)
    assert offenders == []


@pytest.mark.core_isolation
def test_consist4_sensitivity_src_importing_registry_is_flagged() -> None:
    # Both the ``from`` and the plain ``import`` spelling, and the bare token, must be caught.
    assert _status_import_offenders(
        "from tests.plugin.status_registry import CapabilityStatus\n", "x.py"
    )
    assert _status_import_offenders("import tests.plugin.lexicons as lex\n", "x.py")
