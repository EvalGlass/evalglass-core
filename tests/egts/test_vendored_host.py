"""EG-AT0-3 — VendoredHost factory: real vendoring, fail-closed states, clean run.

These tests vendor a real runtime and run it in a subprocess, so they are
``slow`` and ``fixture_e2e``. They prove the factory contract the rest of the
alignment plan builds on: real installer vendoring (not a hand-built tree),
fail-closed authority states, ``evalglass.lock`` at ``evals/``, and a clean
subprocess run that yields observable scorecard/runrecord artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.egts.host_repo import AuthorityState, make_vendored_host

pytestmark = [pytest.mark.fixture_e2e, pytest.mark.slow]


def test_unknown_authority_state_fails_at_construction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown authority_state"):
        make_vendored_host(tmp_path, "bad", authority_state="not_a_state")


def test_host_promoted_gate_with_diluting_trace_is_contradictory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contradictory"):
        make_vendored_host(
            tmp_path,
            "contra",
            authority_state=AuthorityState.HOST_PROMOTED_GATE,
            with_diluting_trace=True,
        )


def test_real_vendoring_lock_at_evals_not_inside_managed(tmp_path: Path) -> None:
    host = make_vendored_host(tmp_path, "lock", authority_state=AuthorityState.FRESH_INFORMATIONAL)
    # Real vendored runtime present.
    assert (host.evals_dir / "_evalglass" / "core").is_dir()
    assert (host.evals_dir / "_evalglass" / "harness").is_dir()
    # NA-37 / P1-7: lock at evals/, never inside the managed tree.
    assert host.lock_path.is_file()
    assert not (host.evals_dir / "_evalglass" / "evalglass.lock").exists()
    # Scaffold writes an empty ledger; runtime never reads it (AUTH-LEDGER decision).
    assert (host.evals_dir / "authority.json").is_file()


def test_fresh_install_first_run_is_informational(tmp_path: Path) -> None:
    host = make_vendored_host(tmp_path, "fresh", authority_state=AuthorityState.FRESH_INFORMATIONAL)
    result = host.run(["run", "--config", "evals/evalglass.yaml"])
    assert result.exit_code == 0, result.stderr
    assert result.scorecard is not None
    assert result.scorecard["verdict"]["verdict"] == "informational"
    assert result.scorecard["verdict"]["ci_should_fail"] is False
    # Real run produced a scored value — informational, not an empty pass.
    assert result.runrecord is not None
    assert any(s["status"] == "scored" for s in result.runrecord["scores"])


def test_host_promoted_gate_passes(tmp_path: Path) -> None:
    host = make_vendored_host(tmp_path, "gate", authority_state=AuthorityState.HOST_PROMOTED_GATE)
    result = host.run(["run", "--config", "evals/evalglass.yaml"])
    assert result.exit_code == 0, result.stderr
    assert result.scorecard is not None
    assert result.scorecard["verdict"]["verdict"] == "pass"
    assert result.scorecard["authority"]["exact_match"]["can_gate"] is True


def test_uncalibrated_judge_cannot_gate(tmp_path: Path) -> None:
    host = make_vendored_host(tmp_path, "judge", authority_state=AuthorityState.UNCALIBRATED_JUDGE)
    result = host.run(["run", "--config", "evals/evalglass.yaml"])
    assert result.exit_code == 0, result.stderr
    assert result.scorecard is not None
    # Scored with a real value, yet not gating — the number-is-not-permission proof.
    authority = result.scorecard["authority"]["faithfulness"]
    assert authority["can_gate"] is False
    assert "judge_uncalibrated" in authority["reasons"]
    assert result.scorecard["verdict"]["verdict"] == "informational"


def test_worst_source_dilutes_gate_to_informational(tmp_path: Path) -> None:
    host = make_vendored_host(
        tmp_path, "dilute", authority_state=AuthorityState.WORST_SOURCE_DILUTED
    )
    result = host.run(["run", "--config", "evals/evalglass.yaml"])
    assert result.exit_code == 0, result.stderr
    assert result.scorecard is not None
    assert result.scorecard["authority"]["exact_match"]["can_gate"] is False
    assert result.scorecard["verdict"]["verdict"] == "informational"


def test_comparable_and_not_comparable_baselines(tmp_path: Path) -> None:
    comp = make_vendored_host(tmp_path, "comp", authority_state=AuthorityState.COMPARABLE_BASELINE)
    comp_result = comp.run(["run", "--config", "evals/evalglass.yaml"])
    assert comp_result.exit_code == 0, comp_result.stderr
    assert comp_result.scorecard is not None
    assert comp_result.scorecard["baseline_state"] == "comparable"

    nc = make_vendored_host(tmp_path, "nc", authority_state=AuthorityState.NOT_COMPARABLE_BASELINE)
    nc_result = nc.run(["run", "--config", "evals/evalglass.yaml"])
    assert nc_result.exit_code == 0, nc_result.stderr
    assert nc_result.scorecard is not None
    assert nc_result.scorecard["baseline_state"] == "not_comparable"
