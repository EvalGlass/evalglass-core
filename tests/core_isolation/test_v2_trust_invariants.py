"""FS-INV — reassert the trust invariants on v2 surfaces (EG-AT1 Slice 6, EG-AT1-6).

The v2 lanes/sinks widen the surface; these guards reassert the four invariants that
keep a green result honest, each with a sensitivity (it fires on the bad case) and a
specificity (the honest case is allowed):

* **FS-INV-1** no non-scored ``0.0`` — invalid/blocked measurement is not a low score,
  no matter how the evidence arrived.
* **FS-INV-2** worst-source authority — a proposed (synthetic-origin) source withholds
  gating even when every other input is approved.
* **FS-INV-3** egress before effects — a sink consults the data policy before any
  connection; ``forbidden``/``missing``/``unknown`` refuse with no attempt.
* **FS-INV-4** hermetic resolve-then-connect — the required path is blocked at DNS
  resolution, before a socket is ever opened.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from evalglass.core import ContractError
from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.harness.lanes import LaneStatus
from tests.fixtures.sinks import TransportSpy, policy_gated_upload
from tests.hermetic import NetworkBlockedError
from tests.scorecard_factory import informational_record, informational_scorecard

# --------------------------------------------------------------------------- #
# FS-INV-1 — no non-scored 0.0
# --------------------------------------------------------------------------- #


def test_no_0_0_even_from_a_lane_fed_evaluator() -> None:
    """Evidence arriving via any path (incl. a lane) cannot smuggle a 0.0 into a
    non-scored Score — the core rejects it at construction."""
    with pytest.raises(ContractError):
        Score(
            metric="m",
            value=0.0,
            status=ScoreStatus.BLOCKED,
            validity=Validity.NOT_MEASURED,
            evaluator_version="lane@1",
        )


def test_real_run_carries_no_non_scored_value(tmp_path: Path) -> None:
    for score in informational_record(tmp_path).scores:
        if score.status is not ScoreStatus.SCORED:
            assert score.value is None, (
                f"{score.metric} is {score.status.value} but carries a value"
            )


# --------------------------------------------------------------------------- #
# FS-INV-2 — worst-source authority (a proposed/synthetic source withholds gating)
# --------------------------------------------------------------------------- #


def _gate_ready_inputs(dataset_status: DatasetStatus) -> AuthorityInputs:
    """A metric otherwise ready to gate (metric gating, threshold approved, policy ok),
    parameterized only by its dataset's source status."""
    return AuthorityInputs(
        dataset_status=dataset_status,
        metric_status=MetricStatus.GATING,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
    )


def test_worst_source_keeps_can_gate_false() -> None:
    resolved = resolve_authority(_gate_ready_inputs(DatasetStatus.PROPOSED))
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


def test_sensitivity_validating_the_source_would_flip_can_gate() -> None:
    """The ONLY change is proposed->validated; can_gate flips — so the proposed
    (synthetic-origin) source is exactly what must keep gating off."""
    proposed = resolve_authority(_gate_ready_inputs(DatasetStatus.PROPOSED))
    validated = resolve_authority(_gate_ready_inputs(DatasetStatus.VALIDATED))
    assert proposed.can_gate is False
    assert validated.can_gate is True


# --------------------------------------------------------------------------- #
# FS-INV-3 — egress before effects
# --------------------------------------------------------------------------- #


def test_sink_refuses_egress_before_request_for_non_egress_policy(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    for policy in (DataPolicy.FORBIDDEN, DataPolicy.MISSING, DataPolicy.UNKNOWN):
        spy = TransportSpy()
        result = policy_gated_upload(scorecard, policy=policy, spy=spy)
        assert result.status is LaneStatus.BLOCKED
        assert spy.attempts == [], f"{policy.value}: a connection was attempted before the refusal"


def test_specificity_permitted_and_redacted_proceed(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    for policy in (DataPolicy.PERMITTED, DataPolicy.REDACTED):
        spy = TransportSpy()
        result = policy_gated_upload(scorecard, policy=policy, spy=spy)
        assert result.status is LaneStatus.RAN
        assert spy.attempts == [("dashboard.invalid", 443)]


def test_sensitivity_effect_before_policy_check_leaks(tmp_path: Path) -> None:
    """An eager sink that connects BEFORE checking policy leaks a connection even for a
    forbidden policy — the anti-pattern egress-before-effects forbids, contrasted with
    the correct order which attempts nothing."""
    scorecard = informational_scorecard(tmp_path)

    def eager_upload(spy: TransportSpy, policy: DataPolicy) -> None:
        spy.connect("dashboard.invalid", 443)  # effect first (WRONG ORDER)
        _ = policy in {DataPolicy.PERMITTED, DataPolicy.REDACTED}

    leaky = TransportSpy()
    eager_upload(leaky, DataPolicy.FORBIDDEN)
    assert leaky.attempts == [("dashboard.invalid", 443)]  # it leaked

    correct = TransportSpy()
    policy_gated_upload(scorecard, policy=DataPolicy.FORBIDDEN, spy=correct)
    assert correct.attempts == []  # policy-before-effect never attempts


# --------------------------------------------------------------------------- #
# FS-INV-4 — hermetic resolve-then-connect
# --------------------------------------------------------------------------- #


def test_hermetic_guard_is_armed() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)
    with (
        pytest.raises(NetworkBlockedError),
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
    ):
        sock.connect(("example.com", 443))


def test_resolve_before_connect_blocks_at_resolve() -> None:
    """A required-path stub that resolves first is stopped at getaddrinfo — the connect
    is never reached, so a leak cannot slip through a resolve-then-connect client."""
    reached_connect = False

    def resolve_then_connect() -> None:
        nonlocal reached_connect
        socket.getaddrinfo("example.com", 443)  # blocked here, before any connect
        reached_connect = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("example.com", 443))

    with pytest.raises(NetworkBlockedError):
        resolve_then_connect()
    assert reached_connect is False
