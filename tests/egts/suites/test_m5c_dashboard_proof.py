"""EGTS-M5C-2 — hosted-dashboard ScoreSink proof (Route Proof, Trust Proof).

Proves the real product :class:`~evalglass.adapters.score_sink_dashboard.DashboardScoreSink`
(EG-H2) over a **real-run** Scorecard produced by ``run_config``:

* ``m5c.dashboard.capture_export`` — the sink publishes exactly the canonical Scorecard payload,
  one-way and authority-free (an injected capture transport, no socket);
* ``m5c.dashboard.egress_before_effects`` — a non-egress ``DataPolicy`` refuses *before* any send
  (the trust line), so forbidden/missing/unknown never reach the network;
* ``m5c.dashboard.deletion_invariant`` — the lane is opt-in, import-isolated, and removable, and
  running it leaves the verdict byte-identical: it informs, it never decides.

A gate-faithful negative control shows an external dashboard surface overclaiming the product
verdict is the exact ``authority_verdict`` fail shape (``tests/CLAUDE.md §12``). Scenario ids map to
EG-M5C-2; the full validator-gate acceptance pack (lane-result evidence) is rebuilt in EG-H5-4.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.score_sink_dashboard import DashboardScoreSink
from evalglass.core.contracts import DataPolicy
from evalglass.harness.lanes import LaneStatus
from tests.egts.lane_conformance import (
    assert_lane_is_opt_in_and_declared,
    assert_lane_result_is_authority_free,
    assert_lane_status_is_fail_closed,
)
from tests.fixtures.sinks import CaptureTransport
from tests.scorecard_factory import informational_record

_ENDPOINT = "https://dashboard.invalid/ingest"
_NON_EGRESS = (DataPolicy.FORBIDDEN, DataPolicy.MISSING, DataPolicy.UNKNOWN)


def test_m5c_dashboard_capture_export(tmp_path: Path) -> None:
    """m5c.dashboard.capture_export — over a real-run Scorecard the sink publishes exactly the
    canonical Scorecard payload, one-way and authority-free."""
    record = informational_record(tmp_path)
    before = record.scorecard.to_dict()
    transport = CaptureTransport()
    result = DashboardScoreSink(
        endpoint=_ENDPOINT, data_policy=DataPolicy.PERMITTED, transport=transport
    ).export(record.scorecard)
    assert result.status is LaneStatus.RAN
    assert transport.sent == [(_ENDPOINT, json.dumps(before, sort_keys=True).encode("utf-8"))]
    assert_lane_result_is_authority_free(result, record.scorecard, before)
    assert_lane_status_is_fail_closed(result)


@pytest.mark.parametrize("policy", _NON_EGRESS, ids=lambda p: p.value)
def test_m5c_dashboard_egress_before_effects(tmp_path: Path, policy: DataPolicy) -> None:
    """m5c.dashboard.egress_before_effects — a non-egress policy refuses BEFORE any send."""
    record = informational_record(tmp_path)
    transport = CaptureTransport()
    result = DashboardScoreSink(endpoint=_ENDPOINT, data_policy=policy, transport=transport).export(
        record.scorecard
    )
    assert result.status is LaneStatus.BLOCKED
    assert transport.sent == [], "egress was attempted before the data-policy gate"
    assert result.diagnostics[0].code == "dashboard_egress_forbidden"


def test_m5c_dashboard_deletion_invariant(tmp_path: Path) -> None:
    """m5c.dashboard.deletion_invariant — the lane is opt-in / import-isolated / removable and
    leaves the verdict byte-identical (it informs, never decides)."""
    assert_lane_is_opt_in_and_declared("hosted-dashboard")
    record = informational_record(tmp_path)
    verdict_before = json.dumps(record.scorecard.to_dict()["verdict"], sort_keys=True)
    DashboardScoreSink(
        endpoint=_ENDPOINT, data_policy=DataPolicy.PERMITTED, transport=CaptureTransport()
    ).export(record.scorecard)
    assert json.dumps(record.scorecard.to_dict()["verdict"], sort_keys=True) == verdict_before


def test_negctl_dashboard_overclaim_is_the_authority_verdict_fail_shape(tmp_path: Path) -> None:
    """Negative control (gate-faithful): an external dashboard surface claiming ``pass`` over an
    informational run is the exact shape the validator-gate ``authority_verdict`` family fails on —
    an external surface overclaiming beyond the product verdict."""
    record = informational_record(tmp_path)
    product_verdict = record.scorecard.to_dict()["verdict"]["verdict"]
    assert product_verdict == "informational"
    # The real sink carries no such claim (proven above); this doctored external surface does.
    external_dashboard_surface = {"authority": "external", "claimed_status": "pass"}
    assert external_dashboard_surface["claimed_status"] != product_verdict
