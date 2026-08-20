"""Smoke tests proving the e2e fixtures work end-to-end (EG-AT6-1).

These exercise the real install + vendored run + bundled-quickstart paths so later journeys can rely
on them. The substantive journey assertions live in EG-AT6-2+.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost

pytestmark = pytest.mark.fixture_e2e


def test_installed_host_first_run_is_informational(
    installed_host: VendoredHost, vendored_run: Callable[..., CliResult]
) -> None:
    result = vendored_run(installed_host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    assert result.scorecard is not None
    assert result.scorecard["verdict"]["verdict"] == "informational"
    assert result.scorecard["verdict"]["ci_should_fail"] is False


def test_make_host_builds_distinct_authority_states(
    make_host: Callable[..., VendoredHost],
) -> None:
    fresh = make_host(AuthorityState.FRESH_INFORMATIONAL)
    proposed = make_host(AuthorityState.PROPOSED_DATASET)
    assert fresh.evals_dir.is_dir()
    assert proposed.evals_dir.is_dir()
    assert fresh.root != proposed.root  # tmp_path-isolated, distinct
    assert fresh.lock_path.is_file()  # evals/evalglass.lock exists (P1-7)


def test_bundled_example_run_is_informational(
    bundled_example_run: Callable[..., CliResult],
) -> None:
    result = bundled_example_run()
    assert result.exit_code == 0
    assert result.scorecard is not None
    assert result.scorecard["verdict"]["verdict"] == "informational"
    # No overclaim in the pre-install quickstart stdout — these terms are prohibited outright.
    lowered = result.stdout.lower()
    for word in ("safe", "production-ready", "proof of correctness"):
        assert word not in lowered, f"quickstart stdout overclaims: {word!r}"
