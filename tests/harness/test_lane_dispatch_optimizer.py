"""The runner-attach seam dispatches the prompt-optimizer handoff SCORE_SINK lane (EG-H2-5/6).

The optimizer handoff is a *local write* (no egress), so — unlike the dashboard upload — its ``RAN``
path runs hermetically through the seam. This proves the foundation seam (ADR 0031) runs the real
``OptimizerHandoffSink`` post-core and folds its ``LaneResult`` into ``RunRecord.lane_results``
without touching the verdict: the run writes ``reports/optimizer/findings.json`` (verdict echoed
verbatim) yet its verdict stays byte-identical to a no-lane run.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core.results import RunRecord
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.lanes import LaneStatus
from evalglass.harness.runner import run_config
from tests.scorecard_factory import _matching_config, informational_record


def _verdict_bytes(record: RunRecord) -> str:
    return json.dumps(record.scorecard.verdict.to_dict(), sort_keys=True)


def test_seam_runs_optimizer_handoff_writes_findings_verdict_immutable(tmp_path: Path) -> None:
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()

    baseline = _verdict_bytes(informational_record(no_lane))

    cfg_data = _matching_config(with_lane)
    cfg_data["lanes"] = [{"name": "optimizer-handoff", "enabled": True, "options": {}}]
    record = run_config(RuntimeConfig.from_mapping(cfg_data), root=with_lane)

    # The lane RAN and is recorded only as a side channel...
    assert [r["status"] for r in record.lane_results] == [LaneStatus.RAN.value]
    assert record.lane_results[0]["lane"] == "optimizer-handoff"
    findings_path = with_lane / "reports" / "optimizer" / "findings.json"
    assert findings_path.is_file()
    # ...the findings echo the run's verdict verbatim...
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    assert findings["verdict"] == record.scorecard.to_dict()["verdict"]
    # ...and it left the verdict byte-identical to the no-lane run.
    assert _verdict_bytes(record) == baseline
