"""Generic stub-backend trace lane + required-path no-SDK contract (EG-AT4-6; plan §5.4).

The three real provider connectors now ship (Langfuse EG-R1, Phoenix EG-R2, LangSmith EG-R3) and
are proven by their own hermetic suites (``test_trace_langfuse/phoenix/langsmith.py``). This suite
is NOT a stand-in for them; it proves the **generic** ``StubBackendTraceSource`` lane (ADR 0018)
and the **required-path no-provider-SDK** boundary that all connectors must respect, over a local
``{"spans": [...]}`` response shaped like each vendor's payload (with a vendor-internal wrapper that
must be dropped at the boundary):

* the stub lane normalizes spans to vendor-neutral ``TraceEnvelope`` records — no vendor object
  reaches the core/evaluators/RunRecord/Scorecard (``check_envelopes_no_vendor_leak``);
* the core branches on no convention/provider token (``check_core_no_convention_branching``);
* no required-tier module imports a provider SDK / network client (``check_no_provider_sdk`` — the
  one guard of the current no-provider-SDK allowlist, so this suite is kept, not folded away);
* a missing endpoint is a clean ``MissingPrerequisite`` skip, and a malformed response is a
  ``Diagnostic`` — never a silent drop or a crash.

Real provider pulls are ``live_lane`` only and never run in the required, hermetic tier.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evalglass.adapters.trace_backend_stub import StubBackendTraceSource
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead
from tests.egts.checkers import (
    check_core_no_convention_branching,
    check_envelopes_no_vendor_leak,
    check_no_provider_sdk,
)
from tests.egts.lane_conformance import SRC_ROOT

#: Each connector's stubbed backend response: a vendor-internal wrapper + open-convention spans.
#: The wrapper key is what must be dropped at the normalization boundary.
_VENDORS = {
    "langfuse": "_langfuse_internal",
    "phoenix": "_phoenix_internal",
    "langsmith": "_langsmith_run",
}


def _vendor_response(wrapper_key: str) -> dict[str, object]:
    return {
        wrapper_key: {"cursor": "opaque-vendor-object"},
        "project_id": "vendor-123",
        "spans": [
            {"trace_id": "t1", "attributes": {"output.value": "hi", "llm.model_name": "m"}},
        ],
    }


def _connector(tmp_path: Path, vendor: str) -> StubBackendTraceSource:
    payload = _vendor_response(_VENDORS[vendor])
    (tmp_path / f"{vendor}.json").write_text(json.dumps(payload), encoding="utf-8")
    return StubBackendTraceSource(
        backend_path=f"{vendor}.json", root=tmp_path, query=f"project={vendor}"
    )


@pytest.mark.parametrize("vendor", sorted(_VENDORS))
def test_connector_normalizes_spans_no_vendor_leak(tmp_path: Path, vendor: str) -> None:
    """Each connector returns TraceEnvelope data with no vendor object carried across."""
    read = _connector(tmp_path, vendor).read()
    assert read.diagnostics == []
    envelopes = [unit.envelope for unit in read.units]
    assert envelopes, "the connector produced no normalized envelopes"
    assert envelopes[0].behavior["output"] == "hi"
    check_envelopes_no_vendor_leak(
        envelopes, forbidden_keys=[_VENDORS[vendor], "project_id", "cursor"]
    )


@pytest.mark.parametrize("vendor", sorted(_VENDORS))
def test_connector_missing_endpoint_skips_clean(vendor: str) -> None:
    """A missing endpoint is a MissingPrerequisite skip, not a crash."""
    root = Path(".")
    with pytest.raises(MissingPrerequisite):
        StubBackendTraceSource(backend_path=None, root=root, query=vendor)


@pytest.mark.parametrize("vendor", sorted(_VENDORS))
def test_connector_malformed_response_is_diagnostic(tmp_path: Path, vendor: str) -> None:
    """Sensitivity: a malformed provider response is a Diagnostic, never a silent drop."""
    (tmp_path / f"{vendor}.json").write_text("{not json", encoding="utf-8")
    read = StubBackendTraceSource(backend_path=f"{vendor}.json", root=tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "backend_malformed_response"


def test_connector_read_carries_no_verdict_or_authority(tmp_path: Path) -> None:
    """A connector yields input evidence only — never a score/verdict/authority surface."""
    read = _connector(tmp_path, "langfuse").read()
    assert isinstance(read, TraceRead)
    for forbidden in ("score", "scores", "verdict", "authority", "ci_should_fail"):
        assert not hasattr(read, forbidden)


def test_connector_core_sees_no_convention_token() -> None:
    """The open-convention mapping stays in the adapter; the core branches on no vendor token."""
    check_core_no_convention_branching(SRC_ROOT)


def test_connector_no_provider_sdk() -> None:
    """No required-tier adapter imports a provider SDK / network client (the opt-in egress lanes
    — live-judge and the hosted-dashboard sink — are exempt; their network client is stdlib
    ``urllib`` behind an injected transport, never a provider SDK)."""
    check_no_provider_sdk(
        SRC_ROOT,
        ["adapters"],
        allow=[
            "adapters/judge_live.py",
            "adapters/judge_openai.py",
            "adapters/score_sink_dashboard.py",
        ],
    )


#: Connectors whose real adapter has NOT shipped yet. All three now ship — Langfuse (EG-R1),
#: Phoenix (EG-R2), and LangSmith (EG-R3) — each with its own ``live_lane`` smoke
#: (``test_trace_langfuse.py`` / ``test_trace_phoenix.py`` / ``test_trace_langsmith.py``), so the
#: placeholder real-pull list is now empty.
_UNBUILT_CONNECTORS: tuple[str, ...] = ()


@pytest.mark.parametrize("vendor", _UNBUILT_CONNECTORS)
@pytest.mark.live_lane
def test_connector_real_pull(vendor: str) -> None:
    """Real provider pull for a not-yet-built connector — ``live_lane`` only; skipped without an
    endpoint.

    No real SDK adapter ships for these yet, so this reports NOT EXERCISED rather than a
    manufactured pass. The collection hook already skips ``live_lane`` unless
    ``EVALGLASS_LIVE_LANES=1``; this further skips without an endpoint so it can never green over a
    missing provider. (Langfuse ships — its real pull is ``test_real_langfuse_pull_smoke``.)
    """
    if not os.environ.get(f"EVALGLASS_{vendor.upper()}_ENDPOINT"):
        pytest.skip(f"no EVALGLASS_{vendor.upper()}_ENDPOINT and no {vendor} connector ships yet")
    raise AssertionError(  # pragma: no cover - guarded by the skip until a connector ships
        f"a {vendor} endpoint was configured but no real connector ships to exercise it"
    )
