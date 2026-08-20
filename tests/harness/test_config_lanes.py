"""The opt-in ``lanes:`` config block (EG-H0-2; ADR 0031).

A run may declare optional extension lanes. Parsing is fail-closed (CLAUDE.md §12)
and conservative-by-default: a lane is **disabled** unless the host explicitly
enables it, an unknown lane name or key is a setup error, and an absent ``lanes:``
key means no lane runs — so existing configs are unaffected.
"""

from __future__ import annotations

import pytest

from evalglass.core import ContractError, DataPolicy
from evalglass.harness.config import LaneConfig, RuntimeConfig

_VALID_LANE = "score-sink-export"  # a real entry in built_in_lanes()


def _metric() -> dict[str, object]:
    return {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
    }


def _config(**over: object) -> dict[str, object]:
    base: dict[str, object] = {"metrics": [_metric()]}
    base.update(over)
    return base


def test_no_lanes_key_means_no_lanes() -> None:
    """An existing config without a ``lanes:`` block parses unchanged — no lane runs."""
    cfg = RuntimeConfig.from_mapping(_config())
    assert cfg.lanes == []


def test_lane_is_disabled_by_default() -> None:
    """Listing a lane never runs it: ``enabled`` defaults to the conservative ``False``."""
    cfg = RuntimeConfig.from_mapping(_config(lanes=[{"name": _VALID_LANE}]))
    assert len(cfg.lanes) == 1
    lane = cfg.lanes[0]
    assert lane.name == _VALID_LANE
    assert lane.enabled is False
    assert lane.data_policy is DataPolicy.UNKNOWN
    assert lane.options == {}


def test_full_lane_config_parses() -> None:
    cfg = RuntimeConfig.from_mapping(
        _config(
            lanes=[
                {
                    "name": _VALID_LANE,
                    "enabled": True,
                    "data_policy": "permitted",
                    "options": {"export_dir": "exports"},
                }
            ]
        )
    )
    lane = cfg.lanes[0]
    assert lane.name == _VALID_LANE
    assert lane.enabled is True
    assert lane.data_policy is DataPolicy.PERMITTED
    assert lane.options == {"export_dir": "exports"}


def test_unknown_lane_name_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes=[{"name": "no-such-lane"}]))


def test_missing_lane_name_fails() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes=[{"enabled": True}]))


def test_unknown_top_level_lane_key_fails() -> None:
    """A typo'd or unsupported lane key must fail closed, never be silently dropped."""
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes=[{"name": _VALID_LANE, "destination": "x"}]))


def test_lane_options_must_be_a_mapping() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes=[{"name": _VALID_LANE, "options": [1, 2]}]))


def test_lane_enabled_must_be_a_bool() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes=[{"name": _VALID_LANE, "enabled": "yes"}]))


def test_lane_entry_must_be_a_mapping() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes=["score-sink-export"]))


def test_lanes_must_be_a_list() -> None:
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(_config(lanes={"name": _VALID_LANE}))


def test_lane_config_is_constructible_directly() -> None:
    """The typed handle is usable on its own (round-trips its declared fields)."""
    lane = LaneConfig(name=_VALID_LANE, enabled=True)
    assert lane.name == _VALID_LANE
    assert lane.enabled is True
    assert lane.options == {}
