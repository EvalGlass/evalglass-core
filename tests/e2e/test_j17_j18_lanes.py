"""J17/J18 re-admitted lanes & sinks journey (EG-AT6-8; alignment plan §F 8.16).

Optional lanes deepen the loop without ever deciding meaning. The runner-attach seam (EG-H0-4)
runs a configured lane **inside** the run, folding its result into ``RunRecord.lane_results`` — a
side channel that leaves the verdict byte-identical; a visible sink is one-way, authority-free, and
verdict-immutable over a *real* run's Scorecard; lane maturity is a capability status, never a
verdict; and generated data displays its governed status (``proposed``), never a run outcome.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import evalglass.harness.runner as runner
from evalglass.adapters.score_sink_export import FileScorecardExportSink
from evalglass.core import DatasetStatus, Scorecard
from evalglass.core.verdict import Verdict
from evalglass.harness.governance import import_synthetic_dataset
from evalglass.harness.lanes import LaneStatus, Maturity, built_in_lanes
from tests.egts.checkers import check_lane_grants_no_authority
from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost
from tests.scorecard_factory import informational_record, record_with_export_lane

pytestmark = pytest.mark.fixture_e2e


def test_j17_lane_runs_inside_the_run_as_a_side_channel(tmp_path: Path) -> None:
    """The seam landed (EG-H0-4): the runner resolves lanes through the framework, so a configured
    lane runs *inside* a run and folds into ``RunRecord.lane_results`` — a side channel that leaves
    the Scorecard (and its verdict) byte-identical to a no-lane run (post-seam FS-DEL-3)."""
    assert "built_in_lanes" in Path(runner.__file__).read_text(encoding="utf-8")
    no_lane = tmp_path / "no_lane"
    no_lane.mkdir()
    with_lane = tmp_path / "with_lane"
    with_lane.mkdir()
    base = informational_record(no_lane)
    record = record_with_export_lane(with_lane, export_dir="exports")
    assert [r["status"] for r in record.lane_results] == [LaneStatus.RAN.value]
    assert record.scorecard.to_dict() == base.scorecard.to_dict()  # verdict/scorecard unchanged


def test_j18_shipped_sink_is_one_way_authority_free_and_verdict_immutable(
    make_host: Callable[..., VendoredHost],
    vendored_run: Callable[..., CliResult],
    tmp_path: Path,
) -> None:
    """A visible export sink renders a *real* run's Scorecard one-way, leaving the verdict whole."""
    host = make_host(AuthorityState.HOST_PROMOTED_GATE)
    result = vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    assert result.scorecard is not None
    scorecard = Scorecard.from_dict(result.scorecard)
    before = scorecard.to_dict()

    lane_result = FileScorecardExportSink(export_dir="exported", root=tmp_path).export(scorecard)

    assert lane_result.status is LaneStatus.RAN
    check_lane_grants_no_authority(lane_result)  # no score/verdict/authority on the result
    written = json.loads((tmp_path / "exported" / "scorecard.export.json").read_text())
    assert written == before  # exact, one-way copy of the Scorecard
    assert scorecard.to_dict() == before  # the Scorecard (and its verdict) is unchanged


def test_lane_maturity_is_a_capability_status_never_a_verdict() -> None:
    verdict_values = {v.value for v in Verdict}
    for lane in built_in_lanes().lanes():
        assert isinstance(lane.maturity, Maturity)
        assert lane.maturity.value not in verdict_values


def test_generated_data_displays_a_governed_status_not_a_verdict() -> None:
    """Synthetic output displays ``proposed`` (a dataset status), never a run verdict."""
    status = import_synthetic_dataset("g", 3, declared_status="validated").status
    assert status is DatasetStatus.PROPOSED
    assert status.value not in {v.value for v in Verdict}
