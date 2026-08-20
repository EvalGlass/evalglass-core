"""The runner-attach seam dispatches the hosted-dashboard SCORE_SINK lane (EG-H2-4).

Proves the foundation seam (ADR 0031) runs the *real* ``DashboardScoreSink`` post-core and folds
its ``LaneResult`` into ``RunRecord.lane_results`` — without touching the verdict:

* a ``forbidden`` data policy blocks the lane *before any network* (hermetic by construction), yet
  the run's verdict stays byte-identical to a no-lane run;
* a missing endpoint cleanly *skips* the lane through the seam (a missing prerequisite is never a
  failed run) — again verdict-immutable.

The seam threads ``LaneConfig.data_policy`` into the SCORE_SINK factory (mirroring the TRACE_SOURCE
path), so the egress gate sees the host-declared policy. No socket is opened in either case; the
``RAN`` publish path (which needs a real transport) is proven hermetically at the adapter level
(``tests/adapters/test_score_sink_dashboard_adapter.py``) with an injected transport.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core.results import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.lanes import LaneStatus
from evalglass.harness.runner import run_config
from tests.scorecard_factory import _matching_config, informational_record

_ENDPOINT = "https://dashboard.invalid/ingest"


def _verdict_bytes(record: RunRecord) -> str:
    return json.dumps(record.scorecard.verdict.to_dict(), sort_keys=True)


def test_seam_blocks_dashboard_on_forbidden_policy_without_network(tmp_path: Path) -> None:
    """A configured dashboard lane with forbidden egress is BLOCKED before any send; verdict
    is byte-identical to a no-lane run (the lane informs, it never decides)."""
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()

    baseline = _verdict_bytes(informational_record(no_lane))

    cfg_data = _matching_config(with_lane)
    cfg_data["lanes"] = [
        {
            "name": "hosted-dashboard",
            "enabled": True,
            "data_policy": "forbidden",
            "options": {"endpoint": _ENDPOINT},
        }
    ]
    record = run_config(RuntimeConfig.from_mapping(cfg_data), root=with_lane)

    assert [r["status"] for r in record.lane_results] == [LaneStatus.BLOCKED.value]
    assert record.lane_results[0]["lane"] == "hosted-dashboard"
    assert record.lane_results[0]["diagnostics"][0]["code"] == "dashboard_egress_forbidden"
    assert _verdict_bytes(record) == baseline


def test_seam_rejects_options_data_policy_override(tmp_path: Path) -> None:
    """The typed ``data_policy`` is authoritative: a conflicting ``options.data_policy`` (the
    classic gate-bypass — forbidden lane, options say permitted) is a BLOCKED setup error, not a
    silent widening of egress. The verdict stays byte-identical to a no-lane run."""
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()

    baseline = _verdict_bytes(informational_record(no_lane))

    cfg_data = _matching_config(with_lane)
    cfg_data["lanes"] = [
        {
            "name": "hosted-dashboard",
            "enabled": True,
            "data_policy": "forbidden",
            "options": {"endpoint": _ENDPOINT, "data_policy": "permitted"},
        }
    ]
    record = run_config(RuntimeConfig.from_mapping(cfg_data), root=with_lane)

    assert [r["status"] for r in record.lane_results] == [LaneStatus.BLOCKED.value]
    assert record.lane_results[0]["diagnostics"][0]["code"] == "lane_setup_failed"
    assert _verdict_bytes(record) == baseline


def test_seam_skips_dashboard_when_endpoint_missing(tmp_path: Path) -> None:
    """An enabled dashboard lane with no endpoint is a clean SKIP through the seam (a missing
    prerequisite never fails a run); the verdict stays byte-identical to a no-lane run."""
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()

    baseline = _verdict_bytes(informational_record(no_lane))

    cfg_data = _matching_config(with_lane)
    cfg_data["lanes"] = [
        {"name": "hosted-dashboard", "enabled": True, "data_policy": "permitted", "options": {}}
    ]
    record = run_config(RuntimeConfig.from_mapping(cfg_data), root=with_lane)

    assert [r["status"] for r in record.lane_results] == [LaneStatus.SKIPPED.value]
    assert record.lane_results[0]["lane"] == "hosted-dashboard"
    assert _verdict_bytes(record) == baseline
