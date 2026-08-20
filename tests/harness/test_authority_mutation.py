"""Authority & baseline mutation are explicit host-owned actions (EG-AT2-5).

Source: alignment test plan §1.2, §8.7, §8.8.

An ordinary ``run`` measures and reports; it never promotes a gate or a baseline.
Only an explicit host-owned command (``baseline update``) changes baseline state,
and ``authority.json`` is never written by a run (it is a host-owned ledger, see
AT0 AUTH-LEDGER decision / ADR 0028). A config that *tries* to gate without the
host preconditions stays informational, and dropping any single precondition keeps
``can_gate`` false with a specific typed reason.

The end-to-end checks drive the real vendored runtime in a clean subprocess
(``fixture_e2e``); the authority matrix is a pure unit test. New file; the frozen
canary ``test_governance.py`` stays byte-stable (AT1 FS-META).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from tests.egts.host_repo import AuthorityState, VendoredHost, make_vendored_host

_RUN = ["run", "--config", "evals/evalglass.yaml"]


def _authority_bytes(host: VendoredHost) -> bytes | None:
    path = host.evals_dir / "authority.json"
    return path.read_bytes() if path.exists() else None


def _baseline_files(host: VendoredHost) -> list[str]:
    baselines = host.evals_dir / "baselines"
    return sorted(p.name for p in baselines.glob("*.json")) if baselines.exists() else []


# --------------------------------------------------------------------------- #
# End-to-end: an ordinary run mutates no host-owned authority/baseline state.
# --------------------------------------------------------------------------- #


@pytest.mark.fixture_e2e
def test_ordinary_run_writes_no_authority_json_or_baseline(tmp_path: Path) -> None:
    """A normal evaluation run leaves ``authority.json`` and ``baselines/`` untouched."""
    host = make_vendored_host(
        tmp_path, "run-immut", authority_state=AuthorityState.HOST_PROMOTED_GATE
    )
    auth_before = _authority_bytes(host)
    assert _baseline_files(host) == []

    result = host.run(_RUN)

    assert result.exit_code == 0
    assert _authority_bytes(host) == auth_before  # authority.json is not a run output
    assert _baseline_files(host) == []  # a run never promotes a baseline


@pytest.mark.fixture_e2e
def test_only_baseline_update_changes_baseline_state(tmp_path: Path) -> None:
    """``baseline update`` is the *only* path that writes a baseline — never a plain run."""
    host = make_vendored_host(
        tmp_path, "bl-explicit", authority_state=AuthorityState.HOST_PROMOTED_GATE
    )
    auth_before = _authority_bytes(host)

    run_result = host.run(_RUN)
    assert run_result.exit_code == 0
    assert _baseline_files(host) == []  # the run wrote no baseline

    update = host.run(
        [
            "baseline",
            "update",
            "--from",
            f"evals/reports/{host.run_id}/runrecord.json",
            "--to",
            "evals/baselines/base.json",
        ]
    )
    assert update.exit_code == 0
    assert "base.json" in _baseline_files(host)  # the explicit host command is the only mutator
    assert _authority_bytes(host) == auth_before  # and it still does not touch authority.json


@pytest.mark.fixture_e2e
def test_config_trying_to_gate_without_authority_stays_informational(tmp_path: Path) -> None:
    """A metric *configured* to gate on a proposed dataset stays informational, never gating."""
    host = make_vendored_host(
        tmp_path, "gate-noauth", authority_state=AuthorityState.PROPOSED_DATASET
    )
    result = host.run(_RUN)

    assert result.exit_code == 0  # informational → exit 0
    assert result.scorecard is not None
    assert result.scorecard["verdict"]["verdict"] == "informational"
    assert result.scorecard["verdict"]["ci_should_fail"] is False
    authority = result.scorecard["authority"]
    assert authority, "expected per-metric authority in the scorecard"
    assert all(not entry["can_gate"] for entry in authority.values())


# --------------------------------------------------------------------------- #
# Unit: dropping any single precondition keeps can_gate false with a typed reason.
# --------------------------------------------------------------------------- #


def _fully_authorized() -> AuthorityInputs:
    """Every gating precondition satisfied — the only state that may gate."""
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=DatasetStatus.VALIDATED,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        judge_calibration=JudgeCalibration.CALIBRATED,
    )


def test_full_preconditions_can_gate() -> None:
    """Specificity: with every precondition met, the metric is eligible to gate."""
    resolved = resolve_authority(_fully_authorized())
    assert resolved.can_gate is True
    assert resolved.reasons == []


_DROP_ONE: list[tuple[dict[str, Any], str]] = [
    ({"metric_status": MetricStatus.DRAFT}, "metric_status=draft"),
    ({"threshold_approval": ThresholdApproval.PROPOSED}, "threshold_proposed"),
    ({"dataset_status": DatasetStatus.PROPOSED}, "dataset_proposed"),
    ({"judge_calibration": JudgeCalibration.UNCALIBRATED}, "judge_uncalibrated"),
]


@pytest.mark.parametrize(("override", "expected_reason"), _DROP_ONE)
def test_dropping_one_precondition_keeps_can_gate_false_with_typed_reason(
    override: dict[str, Any], expected_reason: str
) -> None:
    """Removing any single host precondition keeps the gate closed for a specific reason."""
    inputs = dataclasses.replace(_fully_authorized(), **override)
    resolved = resolve_authority(inputs)
    assert resolved.can_gate is False
    assert expected_reason in resolved.reasons
