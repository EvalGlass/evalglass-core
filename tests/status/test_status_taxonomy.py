"""EG-AT3-1 — scoped capability-status registry parser (alignment plan §7.0, §7.1).

The registry is derived from ``section#capabilities`` of the architecture map. These
tests prove the parser reads only the four capability statuses inside that section,
ignores the authority-ladder badges elsewhere, and fails closed on an unknown badge
or a capability alias claimed under two statuses.
"""

from __future__ import annotations

import pytest

from tests.plugin.capability_registry import (
    CAPABILITY_REGISTRY,
    CAPABILITY_STATUSES,
    StatusParseError,
    build_registry,
    parse_capability_statuses,
)
from tests.plugin.status_registry import CapabilityStatus

pytestmark = pytest.mark.public_surface

# A minimal capabilities section plus an authority section that must be ignored.
_GOOD_HTML = """
<section id="capabilities"><table><tbody>
  <tr><td><span class="status now">now</span></td><td>Shipped.</td>
      <td>Evaluation Core; optional lane framework.</td></tr>
  <tr><td><span class="status next">next</span></td><td>Soon.</td>
      <td>hosted dashboard sink; prompt-optimizer handoff.</td></tr>
</tbody></table></section>
<section id="authority"><table><tbody>
  <tr><td><span class="status blocked">blocked</span></td><td>Gate active.</td></tr>
  <tr><td><span class="status info">informational</span></td><td>No gate.</td></tr>
</tbody></table></section>
"""


def test_real_html_registry_has_all_four_capability_statuses() -> None:
    assert set(CAPABILITY_STATUSES) == set(CapabilityStatus)
    for phrases in CAPABILITY_STATUSES.values():
        assert phrases, "every capability status row carries at least one phrase"


def test_real_html_aliases_each_map_to_exactly_one_status() -> None:
    assert CAPABILITY_REGISTRY  # non-empty
    assert all(isinstance(status, CapabilityStatus) for status in CAPABILITY_REGISTRY.values())
    # Anchor a few known capabilities to the status the architecture map assigns them.
    assert CAPABILITY_REGISTRY["hosted dashboard sink"] is CapabilityStatus.NEXT
    assert CAPABILITY_REGISTRY["prompt-optimizer handoff"] is CapabilityStatus.NEXT
    assert CAPABILITY_REGISTRY["synthetic-data generation"] is CapabilityStatus.PLANNED
    assert CAPABILITY_REGISTRY["annotation workflow ui"] is CapabilityStatus.EXPERIMENTAL


def test_parser_scopes_to_capability_section_and_ignores_authority_ladder() -> None:
    statuses = parse_capability_statuses(_GOOD_HTML)
    assert set(statuses) == {CapabilityStatus.NOW, CapabilityStatus.NEXT}
    registry = build_registry(statuses)
    # The authority-ladder tokens never enter the capability registry.
    assert "blocked" not in {s.value for s in registry.values()}
    assert all(s in (CapabilityStatus.NOW, CapabilityStatus.NEXT) for s in registry.values())


def test_unknown_status_badge_fails_closed() -> None:
    bad = """
    <section id="capabilities"><table><tbody>
      <tr><td><span class="status bogus">bogus</span></td><td>m</td><td>x</td></tr>
    </tbody></table></section>
    """
    with pytest.raises(StatusParseError):
        parse_capability_statuses(bad)


def test_status_badge_with_extra_class_tokens_fails_closed() -> None:
    """An undeclared badge with extra CSS tokens fails closed — never silently skipped."""
    extra = """
    <section id="capabilities"><table><tbody>
      <tr><td><span class="status deferred badge">deferred</span></td><td>m</td><td>x</td></tr>
    </tbody></table></section>
    """
    with pytest.raises(StatusParseError):
        parse_capability_statuses(extra)


def test_duplicate_alias_across_statuses_fails_closed() -> None:
    dup = """
    <section id="capabilities"><table><tbody>
      <tr><td><span class="status now">now</span></td><td>m</td><td>shared thing</td></tr>
      <tr><td><span class="status next">next</span></td><td>m</td><td>shared thing</td></tr>
    </tbody></table></section>
    """
    with pytest.raises(StatusParseError):
        build_registry(parse_capability_statuses(dup))


def test_empty_capability_section_fails_closed() -> None:
    with pytest.raises(StatusParseError):
        parse_capability_statuses("<section id='other'><p>no capabilities</p></section>")
