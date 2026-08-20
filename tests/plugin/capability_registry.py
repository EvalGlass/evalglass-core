"""HTML-derived capability-status registry (EG-AT3-1; alignment test plan §7.0, §7.1).

The product's capability statuses — ``now`` / ``next`` / ``planned`` /
``experimental`` — live in the architecture map's ``section#capabilities`` table.
This module parses **only** that section at import time (GAP-11: the registry is
*derived from the HTML*, never a hand-maintained second copy) so a docs status
change is caught by the cross-surface consistency tests rather than silently
diverging. Status badges elsewhere — notably the authority ladder
(``informational`` / ``blocked`` / ``can_gate``) in ``section#authority`` and the
compound badges in ``section#extensions`` — are deliberately **ignored**.

Test-only data; never imported by ``src/evalglass/**`` (FS-ISO / ST-CONSIST-4).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from tests.plugin.status_registry import CapabilityStatus

#: The architecture map this registry is derived from.
ARCH_HTML = (
    Path(__file__).resolve().parents[2] / "docs" / "evalglass-product-architecture-current.html"
)


class StatusParseError(ValueError):
    """Raised when the capability section badges cannot be parsed honestly."""


class _CapabilitySectionParser(HTMLParser):
    """Collect ``(status_token, capabilities_cell_text)`` rows of ``section#capabilities`` only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str]] = []
        self._in_section = False
        self._in_td = False
        self._row_status: str | None = None
        self._cells: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = dict(attrs)
        if tag == "section" and amap.get("id") == "capabilities":
            self._in_section = True
        if not self._in_section:
            return
        if tag == "tr":
            self._row_status = None
            self._cells = []
        elif tag == "td":
            self._in_td = True
            self._cell = []
        elif tag == "span":
            classes = (amap.get("class") or "").split()
            # The first ``status`` badge of the row is its capability status (col 1). Capture the
            # status token *verbatim* (including odd/extra class tokens) so an undeclared badge such
            # as ``class="status deferred badge"`` fails closed at ``CapabilityStatus(...)`` rather
            # than being silently skipped.
            if "status" in classes and self._row_status is None:
                others = [name for name in classes if name != "status"]
                self._row_status = others[0] if others else ""

    def handle_endtag(self, tag: str) -> None:
        if not self._in_section:
            return
        if tag == "section":
            self._in_section = False
        elif tag == "td":
            self._cells.append("".join(self._cell).strip())
            self._in_td = False
        elif tag == "tr" and self._row_status is not None and self._cells:
            self.rows.append((self._row_status, self._cells[-1]))

    def handle_data(self, data: str) -> None:
        if self._in_section and self._in_td:
            self._cell.append(data)


def _normalize(phrase: str) -> str:
    # Collapse whitespace and drop trailing sentence punctuation ("handoff." -> "handoff"),
    # leaving interior dots intact ("0.1 tagged release").
    return re.sub(r"\s+", " ", phrase).strip().strip(".").strip().lower()


def parse_capability_statuses(html: str) -> dict[CapabilityStatus, tuple[str, ...]]:
    """Parse ``section#capabilities`` into ``{status: (capability phrase, ...)}``.

    A badge whose class token is not one of the four capability statuses fails closed
    (``StatusParseError``) — the parser never invents a status from arbitrary text.
    """
    parser = _CapabilitySectionParser()
    parser.feed(html)
    statuses: dict[CapabilityStatus, tuple[str, ...]] = {}
    for token, capabilities in parser.rows:
        try:
            status = CapabilityStatus(token)
        except ValueError as exc:
            raise StatusParseError(
                f"unknown capability status badge {token!r} in section#capabilities"
            ) from exc
        if status in statuses:
            raise StatusParseError(f"capability status {token!r} appears in more than one row")
        statuses[status] = tuple(
            phrase for raw in capabilities.split(";") if (phrase := _normalize(raw))
        )
    if not statuses:
        raise StatusParseError("no capability rows found in section#capabilities")
    return statuses


def build_registry(
    statuses: dict[CapabilityStatus, tuple[str, ...]],
) -> dict[str, CapabilityStatus]:
    """Invert ``{status: phrases}`` to ``{capability alias: status}``; a dup alias fails closed."""
    registry: dict[str, CapabilityStatus] = {}
    for status, phrases in statuses.items():
        for alias in phrases:
            existing = registry.get(alias)
            if existing is not None and existing is not status:
                raise StatusParseError(
                    f"capability alias {alias!r} appears under two statuses: "
                    f"{existing.value} and {status.value}"
                )
            registry[alias] = status
    return registry


#: ``{CapabilityStatus: (phrase, ...)}`` parsed from the live architecture map.
CAPABILITY_STATUSES = parse_capability_statuses(ARCH_HTML.read_text(encoding="utf-8"))
#: ``{capability alias: CapabilityStatus}`` derived from the same parse.
CAPABILITY_REGISTRY = build_registry(CAPABILITY_STATUSES)

__all__ = [
    "ARCH_HTML",
    "CAPABILITY_REGISTRY",
    "CAPABILITY_STATUSES",
    "CapabilityStatus",
    "StatusParseError",
    "build_registry",
    "parse_capability_statuses",
]
