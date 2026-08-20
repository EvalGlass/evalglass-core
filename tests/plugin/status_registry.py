"""Test-only capability-status taxonomy (EG-AT1-3, FS-SNAP-6 / ST-NOTVERDICT).

The product's public-site **capability status** — ``now`` / ``next`` / ``planned``
/ ``experimental`` — is a *roadmap* axis describing how mature a capability is. It
is emphatically **not** a runtime outcome: not a Verdict, not a ScoreStatus, not a
Validity, not an authority level. To prove that separation without prematurely
adding a ``src/`` symbol, the taxonomy is defined here as **test-only data**, never
imported by ``src/evalglass/**`` (FS-ISO guards the boundary). The real
``ExtensionLane.maturity`` field — the one place this status enters the product —
lands additively in AT3 (ADR 0029), conservative-by-default and never read by the
Verdict Engine, exit mapping, or authority resolution.
"""

from __future__ import annotations

import enum


class CapabilityStatus(enum.StrEnum):
    """How mature a product capability is — a roadmap axis, never a run outcome."""

    NOW = "now"
    NEXT = "next"
    PLANNED = "planned"
    EXPERIMENTAL = "experimental"
