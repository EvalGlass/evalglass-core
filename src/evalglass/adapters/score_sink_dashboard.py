"""Optional hosted-dashboard ScoreSink lane (EG-H2-1; ADR 0031; alignment plan §5.2, delta D5).

An opt-in, deletable SCORE_SINK lane that *publishes* an immutable
:class:`~evalglass.core.Scorecard` to a hosted dashboard endpoint as a **one-way** export. It is a
*next*-status capability — useful evidence packaging, never an authority. The publish transport is
**dependency-injected**, so EvalGlass ships no provider/HTTP SDK and the required tier exercises the
contract with an in-process fake (no socket). The default transport is a standard-library
``urllib`` POST, used only when a real endpoint is configured (a ``live_lane`` path).

Invariants (build contract §6/§8/§9; ADR 0031):

- **Egress-before-effects (the trust line).** The host-declared :class:`DataPolicy` is checked
  **before** the payload is built or the transport is touched. ``forbidden``/``missing``/``unknown``
  (and any unparseable policy) yield ``LaneStatus.BLOCKED`` + a diagnostic and **zero** sends; only
  ``permitted``/``redacted`` may cross the boundary.
- **Read-only.** It serializes ``scorecard.to_dict()`` and can never mutate the verdict, authority,
  or CI exit. A failed publish (outage / malformed / timeout) is a ``BLOCKED`` diagnostic, never a
  fabricated score / ``0.0`` / ``RAN``.
- **A lane, not an authority.** It returns a :class:`~evalglass.harness.lanes.LaneResult` only — no
  ``score``/``verdict``/``authority`` field. No required path imports it; deleting this file leaves
  the local JSON + Markdown reports intact. An absent endpoint raises :class:`MissingPrerequisite`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from evalglass.core import Diagnostic, Scorecard, Severity
from evalglass.core.contracts import DataPolicy
from evalglass.harness.lanes import LaneResult, LaneStatus, MissingPrerequisite

#: The egress set the runtime permits (mirrors the harness ``_EGRESS_OK`` and the export contract).
_EGRESS_OK = frozenset({DataPolicy.PERMITTED, DataPolicy.REDACTED})


@runtime_checkable
class DashboardTransport(Protocol):
    """A one-way publish transport — injected, so the lane needs no built-in HTTP/provider SDK."""

    def send(self, endpoint: str, payload: bytes) -> None: ...


def _coerce_policy(value: str | DataPolicy) -> DataPolicy:
    """Resolve a data policy, failing **closed** to the non-egress ``UNKNOWN`` on any bad value."""
    if isinstance(value, DataPolicy):
        return value
    try:
        return DataPolicy(value)
    except ValueError:
        # An unparseable policy is treated as the most conservative (non-egress) state, never as a
        # silent permit — egress happens only on a genuine ``permitted``/``redacted``.
        return DataPolicy.UNKNOWN


def _redact_endpoint(endpoint: str) -> str:
    """A non-secret label for the destination: ``scheme://host[:port]`` only.

    A configured dashboard endpoint can be a credentialed webhook (``user:pass@``) or carry a token
    in its path/query. Reports and diagnostics are persisted into ``RunRecord.lane_results`` and the
    ``lane_results.json`` sidecar, so they must never echo the raw URL — only the scheme + host are
    safe to record. Falls back to a constant if the endpoint does not parse.
    """
    from urllib.parse import urlsplit  # lazy: stdlib only, kept off the module-import path

    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return "dashboard"
    host = parts.hostname  # excludes any ``user:pass@`` userinfo
    if not host:
        return "dashboard"
    scheme = parts.scheme or "https"
    port = f":{parts.port}" if parts.port else ""
    return f"{scheme}://{host}{port}"


class DashboardScoreSink:
    """Publish the immutable Scorecard JSON to a hosted dashboard endpoint (one-way export)."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        root: Path | None = None,
        data_policy: str | DataPolicy = DataPolicy.UNKNOWN,
        transport: DashboardTransport | None = None,
        name: str = "hosted-dashboard",
    ) -> None:
        if not endpoint:
            # Opt-in: with no endpoint configured the dashboard lane is unavailable (clean skip).
            raise MissingPrerequisite(
                "no dashboard endpoint configured; the hosted-dashboard lane is unavailable"
            )
        self._endpoint = endpoint
        # A non-secret label for any persisted report/diagnostic — the raw endpoint (which can be a
        # credentialed webhook or carry a token) must never reach RunRecord.lane_results.
        self._redacted = _redact_endpoint(endpoint)
        # ``root`` is accepted for the uniform seam factory signature; this sink writes no local
        # file (it publishes over an injected transport), so it is retained only for symmetry.
        self._root = root
        self._data_policy = _coerce_policy(data_policy)
        self._transport = transport
        self._name = name

    def export(self, scorecard: Scorecard) -> LaneResult:
        # EGRESS-BEFORE-EFFECTS (the trust line): refuse a non-egress policy BEFORE building the
        # payload or touching the transport — forbidden/missing/unknown never reach the network.
        if self._data_policy not in _EGRESS_OK:
            return LaneResult(
                lane=self._name,
                status=LaneStatus.BLOCKED,
                report=f"egress refused before request: data_policy={self._data_policy.value}",
                diagnostics=[
                    Diagnostic(
                        code="dashboard_egress_forbidden",
                        severity=Severity.ERROR,
                        message=f"data policy {self._data_policy.value} forbids egress "
                        "to the hosted dashboard",
                    )
                ],
            )
        # Read-only consumption: serialize a copy of the typed Scorecard; the object is untouched.
        payload = json.dumps(scorecard.to_dict(), sort_keys=True).encode("utf-8")
        transport = self._transport if self._transport is not None else _UrllibDashboardTransport()
        try:
            transport.send(self._endpoint, payload)
        except Exception as exc:  # an outage / malformed body / timeout degrades to a diagnostic
            # Scrub the raw endpoint from the exception text before it is persisted — a urllib
            # error can echo the full credentialed URL.
            detail = str(exc).replace(self._endpoint, self._redacted)
            return LaneResult(
                lane=self._name,
                status=LaneStatus.BLOCKED,
                report=f"dashboard upload failed: {detail}",
                diagnostics=[
                    Diagnostic(
                        code="dashboard_upload_failed",
                        severity=Severity.ERROR,
                        message=f"could not publish scorecard to {self._redacted}: {detail}",
                    )
                ],
            )
        return LaneResult(
            lane=self._name,
            status=LaneStatus.RAN,
            report=f"published scorecard to {self._redacted}",
        )


class _UrllibDashboardTransport:
    """The default one-way transport: a stdlib ``urllib`` HTTPS POST (no provider SDK).

    Used only when a real endpoint is configured and no transport is injected — i.e. the
    ``live_lane`` publish path. Plaintext egress is refused (the caller degrades it to a blocked
    diagnostic), so a misconfigured ``http://`` endpoint never leaks the Scorecard in the clear.
    """

    def send(self, endpoint: str, payload: bytes) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError(f"dashboard endpoint must be https, got {endpoint!r}")
        import urllib.request  # lazy: stdlib only, kept off the module-import path

        request = urllib.request.Request(  # noqa: S310 - https-only, host-configured endpoint
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(  # noqa: S310 # nosec B310 - https-only, host-configured
            request, timeout=30
        ) as response:
            response.read(1)  # drain minimally; the dashboard's response body is not consumed
