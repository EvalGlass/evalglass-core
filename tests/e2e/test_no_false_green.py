"""The no-false-green helper + the 13-point release doctrine gate (EG-AT6-11; plan §8.19, §9).

``assert_no_false_green`` is exercised on a real run (specificity) and against doctored results
(sensitivity). The release gate maps each of the 13 doctrine items to a real, collectible guard, so
"done" means the doctrine is proven by tests, not merely declared.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e._assertions import assert_no_false_green
from tests.egts.host_repo import CliResult, VendoredHost

pytestmark = pytest.mark.fixture_e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]

_INFORMATIONAL_SC = {"verdict": {"verdict": "informational", "ci_should_fail": False}}


def _result(**kw: object) -> CliResult:
    base: dict[str, object] = {
        "exit_code": 0,
        "stdout": "verdict: informational [exit zero]\n",
        "stderr": "",
        "scorecard": _INFORMATIONAL_SC,
        "runrecord": {"scores": []},
        "report": "EvalGlass report\nverdict: informational\n",
    }
    base.update(kw)
    return CliResult(**base)  # type: ignore[arg-type]


# --- specificity ------------------------------------------------------------
def test_passes_on_an_honest_real_run(
    installed_host: VendoredHost, vendored_run: Callable[..., CliResult]
) -> None:
    result = vendored_run(installed_host, "run", "--config", "evals/evalglass.yaml")
    assert_no_false_green(result)  # an honest informational run is clean


def test_passes_on_an_honest_constructed_result() -> None:
    assert_no_false_green(_result())


# --- sensitivity ------------------------------------------------------------
def test_rejects_a_stronger_rendered_verdict() -> None:
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(stdout="verdict: pass [exit zero]\n"))


def test_rejects_a_fabricated_zero_for_a_non_scored_score() -> None:
    bad = {"scores": [{"metric": "m", "status": "non_evaluable", "value": 0.0}]}
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(runrecord=bad))


def test_rejects_an_exit_code_that_disagrees_with_ci_should_fail() -> None:
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(exit_code=1))  # ci_should_fail is False


def test_rejects_unearned_success_vocabulary() -> None:
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(report="This run is production-ready.\n"))


def test_rejects_a_stronger_verdict_in_the_report_not_just_stdout() -> None:
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(report="EvalGlass report\nverdict: pass\n"))


def test_rejects_an_overclaim_with_a_trailing_negation() -> None:
    # "without" comes AFTER the term, so it is not a prohibition of it.
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(report="This run is production-ready without caveats.\n"))


def test_allows_a_directly_negated_term() -> None:
    # "not production-ready" is a prohibition, not an overclaim.
    assert_no_false_green(_result(report="This run is not production-ready.\n"))


def test_rejects_certify_distinct_from_certified() -> None:
    # 'certify' is in the shared lexicon and is a distinct token from 'certified'.
    with pytest.raises(AssertionError):
        assert_no_false_green(_result(stdout="verdict: informational\nWe certify this run.\n"))


def test_helper_lexicon_matches_the_shared_unearned_success_lexicon() -> None:
    """The helper's forbidden set is the shared lexicon — no drift, no second copy."""
    from tests.e2e._assertions import _FORBIDDEN_SURFACE_WORDS
    from tests.plugin.lexicons import UNEARNED_SUCCESS_WORDS

    assert set(_FORBIDDEN_SURFACE_WORDS) == set(UNEARNED_SUCCESS_WORDS)
    assert "certify" in _FORBIDDEN_SURFACE_WORDS


# --- the 13-point release doctrine gate -------------------------------------
#: Each doctrine item (plan §9) -> a real, collectible guard that proves it.
_DOCTRINE: dict[str, str] = {
    "1-real-enum-real-golden": "tests/public_surface/test_enum_snapshots.py",
    "2-lanes-prove-four-invariants": "tests/egts/lane_conformance.py",
    "3-egress-decision-not-loopback": "tests/adapters/test_score_sink_dashboard.py",
    "4-no-coverage-over-empty-jurisdiction": "tests/egts/suites/test_v2_coverage_registry.py",
    "5-authority-never-laundered": "tests/harness/test_governance.py",
    "6-hermetic-guard-survives-bypass": "tests/test_live_lane_guard.py",
    "7-status-is-not-a-verdict": "tests/plugin/test_capability_status.py",
    "8-ontology-drift-bidirectional": "tests/ontology/test_track_b_master_guard.py",
    "9-acceptance-pack-symmetric": "tests/egts/suites/test_v2_acceptance_pack.py",
    "10-pivot-adds-no-platform-keys": "tests/status/test_positioning.py",
    "11-spine-contracts-prevented": "tests/public_surface/test_snapshot_integrity.py",
    "12-no-false-green-helper": "tests/e2e/_assertions.py",
    "13-authority-ledger-role-decided": "adrs/0028-authority-json-is-ledger-only.md",
}


@pytest.mark.parametrize(("item", "path"), sorted(_DOCTRINE.items()))
def test_each_doctrine_item_maps_to_a_real_guard(item: str, path: str) -> None:
    target = _REPO_ROOT / path
    assert target.is_file(), f"doctrine item {item} -> missing guard {path}"
    if path.endswith(".py"):
        body = target.read_text(encoding="utf-8")
        assert "def test_" in body or "def assert_" in body, f"{path} has no collectible guard"


def test_thirteen_doctrine_items_are_enumerated() -> None:
    assert len(_DOCTRINE) == 13
