"""J3 fresh install + J2 quickstart — local, informational, bounded first run (EG-AT6-2).

Alignment plan §F 8.1 (J3) and §F 8.3 (J2). The first thing a user sees must be honest: discovery
is read-only, install vendors managed assets without granting authority, and the first run is
``informational`` / exit 0 with **no** ``can_gate`` true and no overclaiming language.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from evalglass.installer.discovery import discover
from tests.e2e._assertions import assert_no_false_green
from tests.egts.host_repo import CliResult, HostRepo, VendoredHost, make_host_repo, snapshot

pytestmark = pytest.mark.fixture_e2e


# --- J3 fresh install -------------------------------------------------------
def test_j3_discover_is_read_only(tmp_path: Path) -> None:
    repo: HostRepo = make_host_repo(tmp_path, "j3-discover")
    before = snapshot(repo.root)
    discover(repo.root)  # read-only inspection
    assert snapshot(repo.root) == before, "discovery mutated the host repo"


def test_j3_install_vendors_managed_assets_and_lock_at_evals(installed_host: VendoredHost) -> None:
    evals = installed_host.evals_dir
    for managed in ("_evalglass/core", "_evalglass/harness", "_evalglass/adapters"):
        assert (evals / managed).is_dir(), f"missing managed tree {managed}"
    # The lock is host-owned at evals/, never inside the managed _evalglass/ (P1-7).
    assert installed_host.lock_path.is_file()
    assert not (evals / "_evalglass" / "evalglass.lock").exists()


def test_j3_authority_json_is_empty_by_default(installed_host: VendoredHost) -> None:
    record = json.loads((installed_host.evals_dir / "authority.json").read_text(encoding="utf-8"))
    assert record == {
        "approved_thresholds": [],
        "calibrated_judges": [],
        "validated_datasets": [],
    }


def test_j3_first_run_is_informational_with_no_active_gate(
    installed_host: VendoredHost, vendored_run: Callable[..., CliResult]
) -> None:
    result = vendored_run(installed_host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    scorecard = result.scorecard
    assert scorecard is not None
    assert scorecard["verdict"]["verdict"] == "informational"
    assert scorecard["verdict"]["ci_should_fail"] is False
    # Nothing gates on a fresh install.
    for metric, authority in scorecard["authority"].items():
        assert authority["can_gate"] is False, f"{metric} gates on a fresh install"
    # The fresh fixture's reference metric produced a real, scored value.
    by_name = {m["metric"]: m for m in scorecard["metrics"]}
    assert "exact_match" in by_name, "the fresh first run is missing its exact_match metric"
    assert by_name["exact_match"]["status_counts"].get("scored")
    assert by_name["exact_match"]["value"] is not None
    assert_no_false_green(result)


# --- J2 quickstart (pre-install) --------------------------------------------
def test_j2_quickstart_is_informational_and_does_not_overclaim(
    bundled_example_run: Callable[..., CliResult],
) -> None:
    result = bundled_example_run()
    assert result.exit_code == 0
    scorecard = result.scorecard
    assert scorecard is not None
    assert scorecard["verdict"]["verdict"] == "informational"
    assert any(m["included_count"] >= 1 for m in scorecard["metrics"])
    # The real scaffolded config exercises a NON-reference metric, scored with a real value.
    by_name = {m["metric"]: m for m in scorecard["metrics"]}
    assert "structural_shape" in by_name, (
        "quickstart did not run its non-reference structural metric"
    )
    assert by_name["structural_shape"]["status_counts"].get("scored")
    # No unearned-success vocabulary in stdout OR the generated report.md.
    surfaces = [result.stdout.lower()]
    assert result.report is not None, "quickstart wrote no report.md"
    surfaces.append(result.report.lower())
    for surface in surfaces:
        for word in ("safe", "production-ready", "proof of correctness", "certified"):
            assert word not in surface, f"quickstart surface overclaims: {word!r}"
    assert_no_false_green(result)
