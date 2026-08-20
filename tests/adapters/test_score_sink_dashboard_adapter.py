"""Real ``DashboardScoreSink`` adapter tests (EG-H2-1/2/3/4).

The hosted-dashboard sink ships this tranche as a *next*-status, stdlib-only SCORE_SINK lane. The
fixture-contract tests in ``test_score_sink_dashboard.py`` proved the *shape* any upload sink must
satisfy; these exercise the **real product class** built behind a dependency-injected transport:

* a **capture** transport proves the byte-exact, one-way, authority-free payload;
* the **egress-before-effects** trust line — a non-egress ``DataPolicy`` is refused *before* the
  transport is ever touched (``forbidden``/``missing``/``unknown`` → ``BLOCKED``, zero sends), with
  a specificity case proving ``permitted``/``redacted`` publish exactly once;
* an **outage** transport proves a failed publish is a ``BLOCKED`` diagnostic, never ``RAN`` / 0.0;
* no provider/HTTP SDK on the required path; a missing endpoint skips; the verdict is untouched.

Required-tier — every transport is injected; no socket is ever opened.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from evalglass.adapters.score_sink_dashboard import DashboardScoreSink, DashboardTransport
from evalglass.core.contracts import DataPolicy
from evalglass.harness.lanes import LaneStatus, MissingPrerequisite
from tests.fixtures.sinks import CaptureTransport, OutageTransport
from tests.scorecard_factory import informational_scorecard as _scorecard

_ENDPOINT = "https://dashboard.invalid/ingest"

#: A non-egress policy must refuse before any effect; only these two may cross the boundary.
_NON_EGRESS = [DataPolicy.FORBIDDEN, DataPolicy.MISSING, DataPolicy.UNKNOWN]
_EGRESS = [DataPolicy.PERMITTED, DataPolicy.REDACTED]

#: Result attributes an upload sink must never carry (it informs, never decides).
_FORBIDDEN_RESULT_ATTRS = ("score", "scores", "value", "verdict", "authority", "ci_should_fail")


def _sink(
    transport: DashboardTransport, *, data_policy: DataPolicy = DataPolicy.PERMITTED
) -> DashboardScoreSink:
    return DashboardScoreSink(
        endpoint=_ENDPOINT, root=None, data_policy=data_policy, transport=transport
    )


# --------------------------------------------------------------------------- #
# Capture transport: byte-exact, one-way, authority-free publish              #
# --------------------------------------------------------------------------- #
def test_dashboard_publishes_exactly_the_canonical_scorecard_payload(tmp_path: Path) -> None:
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    transport = CaptureTransport()
    result = _sink(transport).export(scorecard)
    assert result.status is LaneStatus.RAN
    # Exactly the scorecard, canonically serialized — no more, no less — to the configured endpoint.
    assert transport.sent == [(_ENDPOINT, json.dumps(before, sort_keys=True).encode("utf-8"))]
    # One-way: the Scorecard is consumed read-only.
    assert scorecard.to_dict() == before


def test_dashboard_result_grants_no_authority(tmp_path: Path) -> None:
    result = _sink(CaptureTransport()).export(_scorecard(tmp_path))
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], f"dashboard LaneResult carries forbidden attribute(s): {present}"
    assert isinstance(result.status, LaneStatus)


# --------------------------------------------------------------------------- #
# Egress-before-effects (the trust line)                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("policy", _NON_EGRESS, ids=lambda p: p.value)
def test_dashboard_refuses_non_egress_policy_before_any_send(
    tmp_path: Path, policy: DataPolicy
) -> None:
    """forbidden / missing / unknown → BLOCKED with NO send attempted (the trust line)."""
    transport = CaptureTransport()
    result = _sink(transport, data_policy=policy).export(_scorecard(tmp_path))
    assert result.status is LaneStatus.BLOCKED
    assert transport.sent == [], "egress was attempted before the data-policy gate"
    assert result.diagnostics, "a refused upload must carry a diagnostic"
    assert result.diagnostics[0].code == "dashboard_egress_forbidden"


@pytest.mark.parametrize("policy", _EGRESS, ids=lambda p: p.value)
def test_dashboard_publishes_only_under_egress_policy(tmp_path: Path, policy: DataPolicy) -> None:
    """Specificity: permitted / redacted publishes exactly once."""
    transport = CaptureTransport()
    result = _sink(transport, data_policy=policy).export(_scorecard(tmp_path))
    assert result.status is LaneStatus.RAN
    assert len(transport.sent) == 1


def test_dashboard_unparseable_policy_string_fails_closed_to_no_egress(tmp_path: Path) -> None:
    """A malformed data_policy string is coerced to the conservative (non-egress) end — no send."""
    transport = CaptureTransport()
    sink = DashboardScoreSink(
        endpoint=_ENDPOINT, root=None, data_policy="totally-bogus", transport=transport
    )
    result = sink.export(_scorecard(tmp_path))
    assert result.status is LaneStatus.BLOCKED
    assert transport.sent == []
    assert result.diagnostics[0].code == "dashboard_egress_forbidden"


# --------------------------------------------------------------------------- #
# Outage: a failed publish is BLOCKED, never a fabricated 0.0                  #
# --------------------------------------------------------------------------- #
def test_dashboard_outage_is_blocked_not_zero(tmp_path: Path) -> None:
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    transport = OutageTransport(message="HTTP 503")
    result = _sink(transport).export(scorecard)
    assert result.status is LaneStatus.BLOCKED  # never RAN
    assert transport.sent, "the sink must have attempted the publish before degrading"
    assert result.diagnostics[0].code == "dashboard_upload_failed"
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], "an outage must not fabricate a score/verdict/0.0"
    assert scorecard.to_dict() == before  # the verdict is untouched and still readable


# --------------------------------------------------------------------------- #
# Prerequisite / SDK boundary / deletion invariant                           #
# --------------------------------------------------------------------------- #
def test_dashboard_missing_endpoint_skips_via_missing_prerequisite() -> None:
    with pytest.raises(MissingPrerequisite):
        DashboardScoreSink(endpoint=None, root=None, transport=CaptureTransport())


def test_dashboard_adapter_imports_no_provider_or_http_sdk() -> None:
    """The publish transport is injected, so the adapter needs no provider/HTTP SDK on required
    paths; only the standard library may appear in its source."""
    from evalglass.adapters import score_sink_dashboard as mod

    params = inspect.signature(DashboardScoreSink.__init__).parameters
    assert "transport" in params, "the upload transport must be injectable, not a built-in client"
    src = Path(mod.__file__).read_text(encoding="utf-8")
    banned = (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "langfuse",
        "phoenix",
        "langsmith",
        "openai",
    )
    leaked = [token for token in banned if token in src]
    assert leaked == [], f"the dashboard adapter imports a provider/HTTP SDK: {leaked}"


def test_dashboard_never_persists_the_raw_tokened_endpoint(tmp_path: Path) -> None:
    """A tokened endpoint (a webhook secret in the path/query) is redacted to scheme+host in every
    persisted string, so it cannot leak into ``RunRecord.lane_results``."""
    tokened_endpoint = "https://hooks.example.com/B456/wh-token-value?key=abc"
    leaks = ("wh-token-value", "B456", "key=abc")

    # Success path: the RAN report names only the safe origin.
    ran = DashboardScoreSink(
        endpoint=tokened_endpoint,
        data_policy=DataPolicy.PERMITTED,
        transport=CaptureTransport(),
    ).export(_scorecard(tmp_path))
    assert ran.status is LaneStatus.RAN
    assert "hooks.example.com" in ran.report
    assert all(token not in ran.report for token in leaks), ran.report

    # Outage path: neither the report nor the diagnostic echoes the raw endpoint, even when the
    # transport's exception text contains it verbatim.
    class _EndpointEchoingTransport:
        def send(self, endpoint: str, payload: bytes) -> None:
            raise RuntimeError(f"connection refused to {endpoint}")

    blocked = DashboardScoreSink(
        endpoint=tokened_endpoint,
        data_policy=DataPolicy.PERMITTED,
        transport=_EndpointEchoingTransport(),
    ).export(_scorecard(tmp_path))
    assert blocked.status is LaneStatus.BLOCKED
    persisted = blocked.report + " " + " ".join(d.message for d in blocked.diagnostics)
    assert all(token not in persisted for token in leaks), persisted


def test_redact_endpoint_strips_userinfo_and_path() -> None:
    """``_redact_endpoint`` keeps only scheme+host — userinfo credentials and path/query are
    dropped. The userinfo URL is assembled at runtime so no credentialed literal sits in source."""
    from evalglass.adapters.score_sink_dashboard import _redact_endpoint

    secret = "pw" + "-value"  # assembled, not a literal credential
    endpoint = "https://" + f"user:{secret}@host.example.com" + "/p/tok?q=1"
    redacted = _redact_endpoint(endpoint)
    assert redacted == "https://host.example.com"
    assert all(leak not in redacted for leak in (secret, "tok", "q=1"))


def test_dashboard_deletion_invariant_verdict_identity(tmp_path: Path) -> None:
    """Removable: running the sink leaves the verdict byte-identical — it informs, never decides."""
    scorecard = _scorecard(tmp_path)
    verdict_before = json.dumps(scorecard.to_dict()["verdict"], sort_keys=True)
    _sink(CaptureTransport()).export(scorecard)
    _sink(CaptureTransport(), data_policy=DataPolicy.FORBIDDEN).export(scorecard)
    assert json.dumps(scorecard.to_dict()["verdict"], sort_keys=True) == verdict_before
