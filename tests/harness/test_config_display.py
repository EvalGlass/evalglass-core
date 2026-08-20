"""EG-DX-E1 — host display metadata parses (score-neutral) and is backward-compatible."""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.core._validation import ContractError
from evalglass.harness.config import RuntimeConfig

_BASE_METRIC = {
    "name": "m",
    "evaluator_ref": "structural_shape@1",
    "lens": "non_reference",
    "score_type": "binary",
}


def _config(
    *, metric: dict[str, Any] | None = None, dashboard: dict[str, Any] | None = None
) -> dict[str, Any]:
    m = dict(_BASE_METRIC)
    if metric:
        m.update(metric)
    cfg: dict[str, Any] = {"metrics": [m]}
    if dashboard is not None:
        cfg["dashboard"] = dashboard
    return cfg


def test_absent_display_and_dashboard_are_none() -> None:
    cfg = RuntimeConfig.from_mapping(_config())
    assert cfg.metrics[0].display is None
    assert cfg.dashboard is None


def test_display_metadata_parses() -> None:
    cfg = RuntimeConfig.from_mapping(
        _config(
            metric={
                "display": {
                    "label": "Shape",
                    "workflow": "Ingest",
                    "tier": "runtime",
                    "description": "well-formed?",
                    "order": 3,
                    "docs_url": "docs/x.md",
                    "attention": {"below": 0.8, "note": "watch"},
                }
            }
        )
    )
    display = cfg.metrics[0].display
    assert display is not None
    assert display.label == "Shape"
    assert display.workflow == "Ingest"
    assert display.order == 3
    assert display.attention is not None
    assert display.attention.below == 0.8


def test_dashboard_block_parses() -> None:
    cfg = RuntimeConfig.from_mapping(
        _config(
            dashboard={
                "application": "My app",
                "source_label": "local traces",
                "series": "nightly",
                "composite": {"name": "overall", "version": "1"},
            }
        )
    )
    assert cfg.dashboard is not None
    assert cfg.dashboard.application == "My app"
    assert cfg.dashboard.series == "nightly"
    assert cfg.dashboard.composite == {"name": "overall", "version": "1"}


def test_malformed_display_order_is_a_setup_error() -> None:
    config = _config(metric={"display": {"order": "third"}})
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping(config)
