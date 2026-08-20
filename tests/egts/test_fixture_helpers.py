"""EG-AT0-4 — contract tests for the F-2..F-7 fixture helpers.

Each fixture is proven against a **real product path** (governance funcs, the
authority resolver, the trace adapters) so the helpers can be trusted by later
slices. The trust-critical pair is the sink contract: the capture sink proves the
export shape with no socket, and the transport spy proves egress-before-effects.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from evalglass.adapters import LocalJsonlTraceSource, OpenConventionTraceSource
from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.harness.config import TraceConfig
from evalglass.harness.lanes import LaneResult, LaneStatus
from tests.fixtures.annotations import make_annotation
from tests.fixtures.calibration import CalibrationState, make_calibration
from tests.fixtures.sinks import make_capture_sink, make_transport_spy, policy_gated_upload
from tests.fixtures.synthetic import (
    make_synthetic_request,
    make_synthetic_request_claiming_validated,
)
from tests.fixtures.traces import (
    TraceFixture,
    write_local_trace_jsonl,
    write_local_trace_jsonl_malformed,
    write_openinference_export,
    write_openinference_export_malformed,
    write_otel_export,
    write_otel_export_malformed,
)
from tests.scorecard_factory import informational_scorecard

_FORBIDDEN_LANE_ATTRS = ("score", "scores", "verdict", "authority", "ci_should_fail", "can_gate")


# --- F-6 capture sink: proves the contract WITHOUT a socket --------------------


def test_capture_sink_renders_scorecard_without_a_socket(tmp_path: Path) -> None:
    scorecard = informational_scorecard(tmp_path)
    sink = make_capture_sink()
    result = sink.export(scorecard)
    assert isinstance(result, LaneResult)
    assert result.status is LaneStatus.RAN
    # Captured bytes are exactly the typed scorecard — no invented field.
    assert len(sink.captured) == 1
    assert json.loads(sink.captured[0]) == scorecard.to_dict()
    # Authority-free: the result carries none of the forbidden fields.
    assert not any(hasattr(result, attr) for attr in _FORBIDDEN_LANE_ATTRS)


# --- F-6 transport spy: proves egress-before-effects ---------------------------


@pytest.mark.parametrize(
    "policy",
    [DataPolicy.FORBIDDEN, DataPolicy.MISSING, DataPolicy.UNKNOWN],
)
def test_transport_spy_refuses_egress_before_request(tmp_path: Path, policy: DataPolicy) -> None:
    scorecard = informational_scorecard(tmp_path)
    spy = make_transport_spy()
    result = policy_gated_upload(scorecard, policy=policy, spy=spy)
    # The policy is checked BEFORE any connection is attempted.
    assert result.status is LaneStatus.BLOCKED
    assert spy.attempts == []  # no would-connect recorded


@pytest.mark.parametrize("policy", [DataPolicy.PERMITTED, DataPolicy.REDACTED])
def test_transport_spy_permits_egress_for_egress_policies(
    tmp_path: Path, policy: DataPolicy
) -> None:
    scorecard = informational_scorecard(tmp_path)
    spy = make_transport_spy()
    result = policy_gated_upload(scorecard, policy=policy, spy=spy)
    assert result.status is LaneStatus.RAN
    assert len(spy.attempts) == 1


# --- F-7 calibration: freeze exact reason tokens against resolve_authority ------


def _judge_inputs(calibration: JudgeCalibration) -> AuthorityInputs:
    """A judge metric *configured* to gate, varying only the judge calibration."""
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=DatasetStatus.VALIDATED,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        judge_calibration=calibration,
    )


@pytest.mark.parametrize("state", list(CalibrationState))
def test_calibration_reason_tokens_match_real_authority(
    tmp_path: Path, state: CalibrationState
) -> None:
    fixture = make_calibration(tmp_path, state=state)
    resolved = resolve_authority(_judge_inputs(fixture.judge_calibration))
    if fixture.expected_reason is None:
        # CALIBRATED ⇒ the judge can gate (all other preconditions are met here).
        assert resolved.can_gate is True
    else:
        assert resolved.can_gate is False
        assert fixture.expected_reason in resolved.reasons


def test_calibration_uncalibrated_writes_no_file(tmp_path: Path) -> None:
    assert make_calibration(tmp_path, state=CalibrationState.UNCALIBRATED).path is None


def test_calibration_unknown_state_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown calibration state"):
        make_calibration(tmp_path, state="nonsense")


# --- F-5 annotation ------------------------------------------------------------


@pytest.mark.parametrize("record", [None, "", "   ", "\t", "\n"])
def test_annotation_without_real_record_is_not_authority(record: str | None) -> None:
    assert make_annotation(validation_record=record).is_authority_input is False


def test_annotation_with_host_record_is_authority() -> None:
    assert make_annotation(validation_record="host-rev-7").is_authority_input is True


# --- F-4 synthetic -------------------------------------------------------------


def test_synthetic_request_is_forced_proposed() -> None:
    assert make_synthetic_request().imported().status is DatasetStatus.PROPOSED


def test_synthetic_claiming_validated_is_still_proposed() -> None:
    assert make_synthetic_request_claiming_validated().imported().status is DatasetStatus.PROPOSED


def test_synthetic_negative_size_fails_construction() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        make_synthetic_request(n=-1)


# --- F-2 traces: round-trip through the real adapters --------------------------


def _trace_config(rel: str, fmt: str) -> TraceConfig:
    return TraceConfig.from_mapping({"path": rel, "format": fmt}, 0)


def test_local_trace_well_formed_converges(tmp_path: Path) -> None:
    fx = write_local_trace_jsonl(tmp_path)
    read = LocalJsonlTraceSource(_trace_config(fx.path.name, "local"), tmp_path).read()
    assert len(read.units) == fx.expected_count
    assert read.diagnostics == []


def test_local_trace_malformed_becomes_diagnostic(tmp_path: Path) -> None:
    path = write_local_trace_jsonl_malformed(tmp_path)
    read = LocalJsonlTraceSource(_trace_config(path.name, "local"), tmp_path).read()
    assert read.diagnostics, "a malformed record must surface a diagnostic, never vanish"


@pytest.mark.parametrize(
    ("writer", "malformed", "fmt"),
    [
        (write_otel_export, write_otel_export_malformed, "opentelemetry"),
        (write_openinference_export, write_openinference_export_malformed, "openinference"),
    ],
)
def test_open_convention_traces_converge_and_fail_closed(
    tmp_path: Path,
    writer: Callable[[Path], TraceFixture],
    malformed: Callable[[Path], Path],
    fmt: str,
) -> None:
    fx = writer(tmp_path)
    read = OpenConventionTraceSource(_trace_config(fx.path.name, fmt), tmp_path).read()
    assert len(read.units) == fx.expected_count
    assert read.diagnostics == []
    bad = malformed(tmp_path)
    bad_read = OpenConventionTraceSource(_trace_config(bad.name, fmt), tmp_path).read()
    assert bad_read.diagnostics, "a span missing its output must be a diagnostic"
