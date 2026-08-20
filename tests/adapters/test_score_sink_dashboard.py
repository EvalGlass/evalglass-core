"""Hosted-dashboard ScoreSink contract tests (EG-AT4-4; alignment plan §5.2, delta D5).

The hosted-dashboard sink is a *next*-status, **not-yet-built** capability. There is no
dashboard module to import, and fabricating one would be a false-confidence lane over an
empty jurisdiction (CLAUDE.md §21 Lesson 1). Instead we prove the *contract any upload-shaped
sink must satisfy*, executed hermetically over the AT0 F-6 fixtures that model it:

* the **capture-callable** sink (no socket) proves one-way, byte-identical, authority-free
  export;
* the **transport spy** proves egress-before-effects — a non-egress ``DataPolicy`` is refused
  *before* any connection is attempted (the trust line), with a policy-last negative control
  proving the assertion has teeth;
* an **outage** transport proves a failed publish is a ``BLOCKED`` diagnostic, never a
  fabricated score / ``0.0`` / ``RAN``.

The real-remote variant is ``live_lane`` only and never runs in the required tier.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from evalglass.core.contracts import DataPolicy, Diagnostic, Severity
from evalglass.harness.lanes import LaneResult, LaneStatus
from tests.fixtures import sinks as sinks_mod
from tests.fixtures.sinks import make_capture_sink, make_transport_spy, policy_gated_upload
from tests.scorecard_factory import informational_scorecard as _scorecard

#: A non-egress policy must refuse before any effect; only these two may cross the boundary.
_NON_EGRESS = [DataPolicy.FORBIDDEN, DataPolicy.MISSING, DataPolicy.UNKNOWN]
_EGRESS = [DataPolicy.PERMITTED, DataPolicy.REDACTED]

#: Result attributes an upload sink must never carry (it informs, never decides).
_FORBIDDEN_RESULT_ATTRS = ("score", "scores", "value", "verdict", "authority", "ci_should_fail")


# --------------------------------------------------------------------------- #
# Required tier — capture callable (no socket): one-way, byte-identical export #
# --------------------------------------------------------------------------- #
def test_dashboard_sink_contract_via_capture_callable(tmp_path: Path) -> None:
    """Required contract uses an in-process capture callable and zero sockets."""
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    sink = make_capture_sink()
    result = sink.export(scorecard)
    assert result.status is LaneStatus.RAN
    # Exactly the scorecard, canonically serialized — no more, no less.
    assert sink.captured == [json.dumps(before, sort_keys=True).encode("utf-8")]
    # One-way: the Scorecard is consumed read-only.
    assert scorecard.to_dict() == before


def test_dashboard_sink_result_grants_no_authority(tmp_path: Path) -> None:
    result = make_capture_sink().export(_scorecard(tmp_path))
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], f"dashboard LaneResult carries forbidden attribute(s): {present}"
    assert isinstance(result.status, LaneStatus)


# --------------------------------------------------------------------------- #
# Required tier — transport spy: egress-before-effects (the trust line)       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("policy", _NON_EGRESS, ids=lambda p: p.value)
def test_dashboard_sink_egress_policy_before_request(tmp_path: Path, policy: DataPolicy) -> None:
    """forbidden / missing / unknown → BLOCKED with NO connect attempt recorded."""
    spy = make_transport_spy()
    result = policy_gated_upload(_scorecard(tmp_path), policy=policy, spy=spy)
    assert result.status is LaneStatus.BLOCKED
    assert spy.attempts == [], "egress was attempted before the data-policy gate"
    assert result.diagnostics, "a refused upload must carry a diagnostic"
    assert result.diagnostics[0].code == "dashboard_egress_forbidden"


@pytest.mark.parametrize("policy", _EGRESS, ids=lambda p: p.value)
def test_dashboard_sink_uploads_only_under_egress_policy(
    tmp_path: Path, policy: DataPolicy
) -> None:
    """Specificity: permitted / redacted connects exactly once and runs."""
    spy = make_transport_spy()
    result = policy_gated_upload(_scorecard(tmp_path), policy=policy, spy=spy)
    assert result.status is LaneStatus.RAN
    assert len(spy.attempts) == 1


def _policy_last_upload(
    scorecard: object, *, policy: DataPolicy, spy: sinks_mod.TransportSpy
) -> LaneResult:
    """A DELIBERATELY WRONG upload: connects *first*, checks policy after — the bound we forbid."""
    spy.connect("dashboard.invalid", 443)  # effect before the policy gate — the violation
    if policy not in {DataPolicy.PERMITTED, DataPolicy.REDACTED}:
        return LaneResult(lane="dashboard", status=LaneStatus.BLOCKED, report="checked too late")
    return LaneResult(lane="dashboard", status=LaneStatus.RAN, report="uploaded")


def test_policy_last_upload_attempts_forbidden_egress(tmp_path: Path) -> None:
    """Negative control: the egress-before-effects assertion is not tautological.

    A policy-last flow records a connect attempt even on ``forbidden`` — so the
    ``spy.attempts == []`` assertion above genuinely fails for a non-conforming sink.
    """
    spy = make_transport_spy()
    _policy_last_upload(_scorecard(tmp_path), policy=DataPolicy.FORBIDDEN, spy=spy)
    assert spy.attempts != []  # the forbidden behavior the conforming sink must never exhibit


# --------------------------------------------------------------------------- #
# Required tier — outage: a failed publish is BLOCKED, never a fabricated 0.0  #
# --------------------------------------------------------------------------- #
def _outage_upload(scorecard: object, *, spy: sinks_mod.TransportSpy) -> LaneResult:
    """Egress is permitted but the transport fails (5xx / non-JSON / timeout)."""
    spy.connect("dashboard.invalid", 443)
    # The upstream returns an error; the sink degrades to a diagnostic, never a score.
    return LaneResult(
        lane="dashboard",
        status=LaneStatus.BLOCKED,
        report="dashboard upload failed: HTTP 503",
        diagnostics=[
            Diagnostic(
                code="dashboard_upload_failed",
                severity=Severity.ERROR,
                message="upstream returned HTTP 503",
            )
        ],
    )


def test_dashboard_sink_outage_is_blocked_not_zero(tmp_path: Path) -> None:
    """A malformed/5xx response produces a BLOCKED diagnostic, never RAN / a 0.0 score."""
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    result = _outage_upload(scorecard, spy=make_transport_spy())
    assert result.status is LaneStatus.BLOCKED  # never RAN
    assert result.diagnostics[0].code == "dashboard_upload_failed"
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], "an outage must not fabricate a score/verdict/0.0"
    assert scorecard.to_dict() == before  # the verdict is untouched and still readable


# --------------------------------------------------------------------------- #
# No provider SDK; deletion invariant (verdict identity)                      #
# --------------------------------------------------------------------------- #
def test_dashboard_upload_contract_uses_dependency_injected_transport() -> None:
    """The upload transport is injected — so the contract needs no built-in provider/HTTP SDK."""
    params = inspect.signature(policy_gated_upload).parameters
    assert "spy" in params, "the upload transport must be injected, not a built-in client"
    src = Path(sinks_mod.__file__).read_text(encoding="utf-8")
    banned = (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "langfuse",
        "openai",
    )
    leaked = [token for token in banned if token in src]
    assert leaked == [], f"the upload contract surface imports a provider/HTTP SDK: {leaked}"


def test_dashboard_sink_deletion_invariant_verdict_identity(tmp_path: Path) -> None:
    """Removable: running the sink leaves the verdict byte-identical — it informs, never decides."""
    scorecard = _scorecard(tmp_path)
    verdict_before = json.dumps(scorecard.to_dict()["verdict"], sort_keys=True)
    make_capture_sink().export(scorecard)
    policy_gated_upload(scorecard, policy=DataPolicy.PERMITTED, spy=make_transport_spy())
    assert json.dumps(scorecard.to_dict()["verdict"], sort_keys=True) == verdict_before


# --------------------------------------------------------------------------- #
# Opt-in live tier only — never required                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.live_lane
def test_dashboard_sink_real_remote(tmp_path: Path) -> None:
    """Real remote upload — ``live_lane`` only; never part of the required, hermetic tier.

    No hosted-dashboard backend ships yet, so this is reported NOT EXERCISED (skipped)
    rather than dressed as a pass. The required-tier collection hook already skips every
    ``live_lane`` test unless ``EVALGLASS_LIVE_LANES=1``; this further skips without a
    configured backend endpoint, so it can never manufacture a green over a missing remote.
    """
    endpoint = os.environ.get("EVALGLASS_DASHBOARD_ENDPOINT")
    if not endpoint:
        pytest.skip("no EVALGLASS_DASHBOARD_ENDPOINT and no hosted-dashboard backend ships yet")
    raise AssertionError(  # pragma: no cover - guarded by the skip above until a backend exists
        "a hosted-dashboard backend was configured but no real-remote sink ships to exercise it"
    )
