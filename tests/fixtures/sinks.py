"""F-6 — sink stubs that prove the export contract *without* a socket (EG-AT0-4).

Two distinct stubs, deliberately separate (alignment plan §3.2 F-6, fix C4):

* :class:`CaptureSink` — a one-way export sink built around an injected
  *write-capture callable* (no socket at all). It proves a sink renders exactly
  ``scorecard.to_dict()`` and returns an authority-free ``LaneResult``.
* :class:`TransportSpy` — records "would-connect" targets *without connecting*,
  so an upload-shaped sink can be proven to consult :class:`DataPolicy` and
  refuse ``forbidden``/``missing``/``unknown`` **before** any request is built.

Loopback/real-remote variants belong to the ``live_lane`` tier and are NOT here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from evalglass.core import Scorecard
from evalglass.core.contracts import DataPolicy, Diagnostic, Severity
from evalglass.harness.lanes import LaneResult, LaneStatus

#: The egress set the runtime permits (mirrors the harness ``_EGRESS_OK``).
_EGRESS_OK = frozenset({DataPolicy.PERMITTED, DataPolicy.REDACTED})


@dataclass
class CaptureSink:
    """A one-way export sink whose transport is an in-process callable (no socket)."""

    name: str = "capture"
    captured: list[bytes] = field(default_factory=list)

    def export(self, scorecard: Scorecard) -> LaneResult:
        payload = json.dumps(scorecard.to_dict(), sort_keys=True).encode("utf-8")
        self.captured.append(payload)
        return LaneResult(lane=self.name, status=LaneStatus.RAN, report="captured scorecard")


def make_capture_sink() -> CaptureSink:
    return CaptureSink()


@dataclass
class TransportSpy:
    """Records attempted connections without ever opening a socket."""

    attempts: list[tuple[str, int]] = field(default_factory=list)

    def connect(self, host: str, port: int) -> None:
        self.attempts.append((host, port))


def make_transport_spy() -> TransportSpy:
    return TransportSpy()


@dataclass
class CaptureTransport:
    """A one-way dashboard ``send(endpoint, payload)`` transport that captures bytes in-process.

    Injected into the real :class:`~evalglass.adapters.score_sink_dashboard.DashboardScoreSink`
    so the required tier proves the egress contract with no socket (the publish is recorded, not
    sent). It is the ``send``-shaped analogue of :class:`CaptureSink`.
    """

    sent: list[tuple[str, bytes]] = field(default_factory=list)

    def send(self, endpoint: str, payload: bytes) -> None:
        self.sent.append((endpoint, payload))


@dataclass
class OutageTransport:
    """A dashboard transport that always fails — models a 5xx / malformed body / timeout.

    Records every (would-be) send so a test can assert the sink *tried* to publish and then
    degraded the failure to a ``BLOCKED`` diagnostic rather than a fabricated score.
    """

    message: str = "HTTP 503"
    sent: list[tuple[str, bytes]] = field(default_factory=list)

    def send(self, endpoint: str, payload: bytes) -> None:
        self.sent.append((endpoint, payload))
        raise RuntimeError(self.message)


def policy_gated_upload(
    scorecard: Scorecard,
    *,
    policy: DataPolicy,
    spy: TransportSpy,
    endpoint: tuple[str, int] = ("dashboard.invalid", 443),
) -> LaneResult:
    """Reference upload flow proving egress-before-effects with a transport spy.

    The data policy is checked **before** the request/connection is constructed:
    a non-egress policy returns ``BLOCKED`` and the spy records *no* attempt.
    This is the contract the AT4 hosted-dashboard sink must satisfy.
    """
    if policy not in _EGRESS_OK:
        return LaneResult(
            lane="dashboard",
            status=LaneStatus.BLOCKED,
            report=f"egress refused before request: data_policy={policy.value}",
            diagnostics=[
                Diagnostic(
                    code="dashboard_egress_forbidden",
                    severity=Severity.ERROR,
                    message=f"data policy {policy.value} forbids egress",
                )
            ],
        )
    # Egress permitted — only now is the connection attempted.
    spy.connect(*endpoint)
    json.dumps(scorecard.to_dict(), sort_keys=True)  # render the (would-be) body
    return LaneResult(lane="dashboard", status=LaneStatus.RAN, report="uploaded scorecard")
