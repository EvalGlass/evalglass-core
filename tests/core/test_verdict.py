"""The single Verdict Engine + verdict matrix (EG-M0-5b).

Only the Verdict Engine turns resolved authority + measured values + approved
thresholds into a run outcome (``CLAUDE.md §11``; ``architecture.md §6``):

* no active gate                              -> informational (ci_should_fail=false)
* active gate, valid, meets threshold         -> pass         (false)
* active gate, valid, misses threshold        -> fail         (true)
* active gate blocked / no value / no threshold -> blocked     (true)

A ``pass`` is never emitted while any active gate fails or is blocked. When both a
blocked and a failing gate are present, the run reports ``blocked`` (it cannot make
an honest claim) — but both lists are preserved so nothing is hidden.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.authority import AuthorityLevel, ResolvedAuthority
from evalglass.core.contracts import ContractError
from evalglass.core.registry import Direction
from evalglass.core.verdict import GateInput, Verdict, VerdictPayload, decide_verdict

_GATING = ResolvedAuthority(can_gate=True, level=AuthorityLevel.GATING, blocked=False)
_BLOCKED = ResolvedAuthority(
    can_gate=False, level=AuthorityLevel.GATING, blocked=True, reasons=["x"]
)
_INFO = ResolvedAuthority(can_gate=False, level=AuthorityLevel.INFORMATIONAL, blocked=False)


def _gate(
    metric: str,
    resolved: ResolvedAuthority,
    value: float | None = None,
    threshold: float | None = None,
    direction: Direction = Direction.HIGHER_IS_BETTER,
) -> GateInput:
    return GateInput(
        metric=metric, resolved=resolved, value=value, threshold=threshold, direction=direction
    )


# --- the verdict matrix -----------------------------------------------------


@pytest.mark.verdict_matrix
def test_no_active_gate_is_informational() -> None:
    payload = decide_verdict([_gate("m", _INFO, value=0.0)])
    assert payload.verdict is Verdict.INFORMATIONAL
    assert payload.ci_should_fail is False
    assert payload.informational_metrics == ["m"]


@pytest.mark.verdict_matrix
def test_active_gate_meeting_threshold_passes() -> None:
    payload = decide_verdict([_gate("m", _GATING, value=0.9, threshold=0.8)])
    assert payload.verdict is Verdict.PASS
    assert payload.ci_should_fail is False
    assert payload.passing_gates == ["m"]


@pytest.mark.verdict_matrix
def test_active_gate_missing_threshold_fails() -> None:
    payload = decide_verdict([_gate("m", _GATING, value=0.5, threshold=0.8)])
    assert payload.verdict is Verdict.FAIL
    assert payload.ci_should_fail is True
    assert payload.failing_gates == ["m"]


@pytest.mark.verdict_matrix
def test_lower_is_better_direction() -> None:
    # e.g. a latency/error-rate metric: lower passes.
    low = decide_verdict([_gate("m", _GATING, 0.2, 0.5, Direction.LOWER_IS_BETTER)])
    high = decide_verdict([_gate("m", _GATING, 0.7, 0.5, Direction.LOWER_IS_BETTER)])
    assert low.verdict is Verdict.PASS
    assert high.verdict is Verdict.FAIL
    # the reason must reflect the direction: the value is ABOVE the allowed max
    assert high.reasons["m"] == ["above_threshold"]


@pytest.mark.verdict_matrix
def test_blocked_gate_blocks() -> None:
    payload = decide_verdict([_gate("m", _BLOCKED)])
    assert payload.verdict is Verdict.BLOCKED
    assert payload.ci_should_fail is True
    assert payload.blocked_gates == ["m"]


@pytest.mark.verdict_matrix
def test_active_gate_with_no_value_is_blocked() -> None:
    payload = decide_verdict([_gate("m", _GATING, value=None, threshold=0.8)])
    assert payload.verdict is Verdict.BLOCKED
    assert payload.blocked_gates == ["m"]


@pytest.mark.verdict_matrix
def test_active_gate_with_no_threshold_is_blocked() -> None:
    payload = decide_verdict([_gate("m", _GATING, value=0.9, threshold=None)])
    assert payload.verdict is Verdict.BLOCKED


# --- precedence -------------------------------------------------------------


def test_blocked_outranks_fail_but_both_are_recorded() -> None:
    payload = decide_verdict([_gate("fails", _GATING, 0.1, 0.8), _gate("blocked", _BLOCKED)])
    assert payload.verdict is Verdict.BLOCKED
    assert payload.failing_gates == ["fails"]
    assert payload.blocked_gates == ["blocked"]


def test_fail_outranks_pass() -> None:
    payload = decide_verdict([_gate("ok", _GATING, 0.9, 0.8), _gate("bad", _GATING, 0.1, 0.8)])
    assert payload.verdict is Verdict.FAIL


def test_pass_with_an_informational_metric_still_passes() -> None:
    payload = decide_verdict([_gate("ok", _GATING, 0.9, 0.8), _gate("info", _INFO, 0.0)])
    assert payload.verdict is Verdict.PASS
    assert payload.informational_metrics == ["info"]


def test_empty_run_is_informational() -> None:
    assert decide_verdict([]).verdict is Verdict.INFORMATIONAL


# --- contract ---------------------------------------------------------------


def test_payload_round_trips() -> None:
    payload = decide_verdict([_gate("fails", _GATING, 0.1, 0.8), _gate("blocked", _BLOCKED)])
    assert VerdictPayload.from_dict(json.loads(json.dumps(payload.to_dict()))) == payload


@pytest.mark.public_surface
def test_payload_snapshot_shape() -> None:
    """The VerdictPayload public JSON shape is stable (CLAUDE.md §18)."""
    payload = decide_verdict([_gate("acc", _GATING, value=0.95, threshold=0.9)])
    assert payload.to_dict() == {
        "verdict": "pass",
        "ci_should_fail": False,
        "passing_gates": ["acc"],
        "failing_gates": [],
        "blocked_gates": [],
        "informational_metrics": [],
        "reasons": {},
    }


def test_payload_from_dict_rejects_unknown_verdict() -> None:
    data = decide_verdict([]).to_dict()
    data["verdict"] = "greenish"
    with pytest.raises(ContractError):
        VerdictPayload.from_dict(data)


def test_payload_rejects_contradictory_state() -> None:
    """A mutated payload (pass + a failing gate) must fail closed, not pass."""
    data = decide_verdict([_gate("ok", _GATING, 0.9, 0.8)]).to_dict()  # a real pass
    data["failing_gates"] = ["m"]  # ...but now claims a failing gate
    with pytest.raises(ContractError):
        VerdictPayload.from_dict(data)


def test_payload_rejects_mismatched_ci_flag() -> None:
    data = decide_verdict([_gate("bad", _GATING, 0.1, 0.8)]).to_dict()  # fail, ci=True
    data["ci_should_fail"] = False
    with pytest.raises(ContractError):
        VerdictPayload.from_dict(data)
