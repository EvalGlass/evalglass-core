"""FS-SNAP-7 — freeze ExtensionLane metadata + the built-in lane roster (EG-AT1-3).

``ExtensionLane.to_dict()`` is the public lane-metadata contract; its base keyset is
frozen (AT3 may add ``group``/``maturity`` *additively*, via a deliberate update).
The ``built_in_lanes()`` roster is frozen additive-only and round-trips, so a lane
cannot quietly gain authority-bearing fields or change its declared port/module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.harness.lanes import ExtensionLane, built_in_lanes

_SNAP = Path(__file__).parent / "_snapshots"


def _load(name: str) -> Any:
    return json.loads((_SNAP / name).read_text(encoding="utf-8"))


def _roster() -> list[ExtensionLane]:
    return built_in_lanes().lanes()


@pytest.mark.public_surface
def test_extension_lane_base_keyset_frozen() -> None:
    keys = sorted(_roster()[0].to_dict())
    assert keys == _load("extension_lane_keys.json")


@pytest.mark.public_surface
def test_lane_roster_frozen_additive_only() -> None:
    """The FULL metadata of every built-in lane is frozen (not just name/port/module).

    Freezing only name/port/module/factory would let a lane's boundary, deletion_rule,
    purpose, prerequisites, or optional_dependencies drift unnoticed.
    """
    roster = [lane.to_dict() for lane in _roster()]
    assert roster == _load("lane_roster.json")


@pytest.mark.public_surface
def test_every_built_in_lane_round_trips() -> None:
    for lane in _roster():
        assert ExtensionLane.from_dict(lane.to_dict()) == lane


@pytest.mark.public_surface
def test_sensitivity_extra_lane_key_drifts() -> None:
    """An added key beyond the frozen base keyset drifts the snapshot."""
    keys = sorted([*_roster()[0].to_dict(), "dashboard_url"])
    assert keys != _load("extension_lane_keys.json")
