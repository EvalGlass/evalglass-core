"""Hermetic Langfuse connector contract (EG-R1; ADR 0034).

Proves the Langfuse :class:`~evalglass.harness.ports.TraceSource` over the local fixture family
(``fixtures/connectors/langfuse.json``) — no ``langfuse`` SDK, no socket. The live SDK call is
injected as ``fetch``; here it returns fixture payloads so the mapping, the egress gate, and the
fail-closed paths are all exercised hermetically. The real-pull path is ``live_lane`` (EG-R1-6).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters.trace_langfuse import LangfuseTraceSource
from evalglass.harness.lanes import MissingPrerequisite, built_in_lanes
from evalglass.harness.ports import TraceRead, TraceUnit
from tests.egts.checkers import check_envelopes_no_vendor_leak

_FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "connectors" / "langfuse.json").read_text(
        encoding="utf-8"
    )
)
_WRAPPER_KEYS = _FIXTURE["vendor_wrapper_keys"]


def _source(fetch: Any, *, data_policy: str = "permitted") -> LangfuseTraceSource:
    # Flattened options exactly as the runner seam passes them: factory(data_policy=..., **options).
    return LangfuseTraceSource(endpoint="https://lf.example", data_policy=data_policy, fetch=fetch)


def _as_expected(unit: TraceUnit) -> dict[str, Any]:
    """Project a produced ``TraceUnit`` to the fixture's declared ``expected`` shape."""
    return {
        "unit": {
            "unit_id": unit.unit.unit_id,
            "kind": unit.unit.kind.value,
            "trace_id": unit.unit.trace_id,
        },
        "behavior": dict(unit.envelope.behavior),
        "metadata": dict(unit.envelope.metadata),
    }


def test_good_payload_matches_declared_expected_output() -> None:
    read = _source(lambda: _FIXTURE["good"]).read()
    assert read.diagnostics == []
    assert [_as_expected(u) for u in read.units] == _FIXTURE["expected"]


def test_trace_level_payload_maps_workflow_output() -> None:
    # The real Langfuse public list endpoint returns observations as bare IDs; the trace-level
    # output is the workflow result and must still map, tagged with the trace name (workflow) and
    # session so downstream evaluation can dispatch per workflow (EG-R1 live-hardening).
    read = _source(lambda: _FIXTURE["trace_level"]).read()
    assert read.diagnostics == []
    assert [_as_expected(u) for u in read.units] == _FIXTURE["trace_level_expected"]
    env = read.units[0].envelope
    assert env.metadata["trace_name"] == "entity-extraction"
    assert env.metadata["session_id"] == "INC_x"


def test_good_payload_now_carries_trace_name() -> None:
    # Observation-level mapping still works and now also propagates the trace name to metadata.
    read = _source(lambda: _FIXTURE["good"]).read()
    assert read.units[0].envelope.metadata.get("trace_name") == "chat"


def test_vendor_wrapper_payload_drops_vendor_objects() -> None:
    read = _source(lambda: _FIXTURE["vendor_wrapper"]).read()
    assert read.diagnostics == []
    # Same normalized output as the clean payload — the wrapper keys never cross the boundary.
    assert [_as_expected(u) for u in read.units] == _FIXTURE["expected"]
    check_envelopes_no_vendor_leak([u.envelope for u in read.units], forbidden_keys=_WRAPPER_KEYS)


def test_envelope_carries_connector_uniform_fields() -> None:
    read = _source(lambda: _FIXTURE["good"]).read()
    env = read.units[0].envelope
    assert env.source == "langfuse-trace"
    assert env.data_policy.value == "permitted"
    assert env.provenance == {"trace": "langfuse-trace", "provider": "langfuse"}


def test_missing_endpoint_is_missing_prerequisite_skip() -> None:
    with pytest.raises(MissingPrerequisite):
        LangfuseTraceSource(data_policy="permitted", fetch=lambda: _FIXTURE["good"])


def test_lane_factory_is_runner_compatible() -> None:
    """The runner seam resolves the lane and calls ``factory(root=root, data_policy=..., **opts)``
    (flattened). Construction must succeed; with no langfuse SDK installed the default fetch is a
    clean ``MissingPrerequisite`` skip — never a ``lane_setup_failed`` from a signature mismatch."""
    factory = built_in_lanes().resolve("langfuse-trace")
    source = factory(root=Path("."), data_policy="permitted", endpoint="https://lf.example")
    with pytest.raises(MissingPrerequisite):
        source.read()  # default fetch → lazy_import('langfuse') absent → propagated skip


@pytest.mark.parametrize("policy", ["forbidden", "missing", "unknown"])
def test_forbidden_policy_refuses_before_any_fetch(policy: str) -> None:
    calls: list[int] = []

    def spy() -> Any:
        calls.append(1)
        return _FIXTURE["good"]

    read = _source(spy, data_policy=policy).read()
    assert calls == [], "egress-before-effects: a non-egress policy must not call the provider"
    assert read.units == []
    assert read.diagnostics[0].code == "langfuse_egress_forbidden"


def test_malformed_response_is_a_diagnostic() -> None:
    read = _source(lambda: {"unexpected": "shape"}).read()
    assert read.units == []
    assert read.diagnostics[0].code == "langfuse_malformed_response"


def test_fetch_failure_is_a_diagnostic_not_a_crash() -> None:
    def boom() -> Any:
        raise RuntimeError("provider down")

    read = _source(boom).read()
    assert read.units == []
    assert read.diagnostics[0].code == "langfuse_malformed_response"


def test_missing_field_observation_is_a_diagnostic() -> None:
    read = _source(lambda: _FIXTURE["missing_field"]).read()
    assert read.units == []  # no LLM output on the observation → mapping-incomplete diagnostic
    assert read.diagnostics


def test_malformed_trace_entry_surfaces_a_diagnostic_not_silent_empty() -> None:
    """A non-empty malformed response (a trace with no observations list) must not read as an empty
    clean import — it surfaces a diagnostic so the lane never hides that nothing was imported."""
    read = _source(lambda: {"data": [{"id": "trace-x", "observations": "not-a-list"}]}).read()
    assert read.units == []
    assert read.diagnostics, "a malformed trace entry must surface a diagnostic, not vanish"
    assert read.diagnostics[0].code == "langfuse_malformed_response"


def test_empty_payload_yields_no_units_no_diagnostics() -> None:
    read = _source(lambda: _FIXTURE["empty"]).read()
    assert isinstance(read, TraceRead)
    assert read.units == []
    assert read.diagnostics == []


#: Host-owned env-var NAMES the lane resolves at run time — never secrets (the connector boundary
#: rejects literal secret values via a name regex). Referenced rather than inlined next to the
#: credential keys so the secret scanner does not misread the mapping (S6418 false positive).
_PUBLIC_KEY_ENV, _SECRET_KEY_ENV = "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"


def _install_fake_langfuse(
    monkeypatch: pytest.MonkeyPatch, *, payload: Any, calls: dict[str, Any]
) -> None:
    """Inject a fake ``langfuse`` module so the DEFAULT fetch path runs with no SDK/socket. The fake
    ``Langfuse`` records its construction kwargs so a test can prove credentials are passed
    explicitly (no ambient pickup)."""
    import sys
    import types

    class _FakeLangfuse:
        def __init__(self, **kwargs: Any) -> None:
            calls["init"] = kwargs
            self.api = types.SimpleNamespace(
                trace=types.SimpleNamespace(list=lambda **_kw: payload)
            )

    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(Langfuse=_FakeLangfuse))


def test_default_fetch_requires_both_credentials_before_any_client_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permitted, endpoint-only config (no credentials) is a clean MissingPrerequisite skip —
    Langfuse has no anonymous read API (ADR 0034), so the declared public_key/secret_key are
    enforced BEFORE any client construction, never a keyless/ambient-credential pull."""
    monkeypatch.delenv(_PUBLIC_KEY_ENV, raising=False)
    monkeypatch.delenv(_SECRET_KEY_ENV, raising=False)
    calls: dict[str, Any] = {}
    _install_fake_langfuse(monkeypatch, payload=_FIXTURE["good"], calls=calls)
    source = LangfuseTraceSource(endpoint="https://lf.example", data_policy="permitted")
    with pytest.raises(MissingPrerequisite):
        source.read()
    assert calls == {}, "no client was constructed when credentials were missing"


def test_default_fetch_passes_resolved_credentials_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With both credentials declared + resolved, the default fetch constructs the client with them
    explicitly (blocking ambient SDK env pickup) and maps the result."""
    # Neutral resolved values (not credential-shaped) compared via variables, so the secret scanner
    # does not flag the comparison as a hard-coded secret (S105).
    public_value, secret_value = "resolved-public-ref", "resolved-private-ref"
    monkeypatch.setenv(_PUBLIC_KEY_ENV, public_value)
    monkeypatch.setenv(_SECRET_KEY_ENV, secret_value)
    calls: dict[str, Any] = {}
    _install_fake_langfuse(monkeypatch, payload=_FIXTURE["good"], calls=calls)
    source = LangfuseTraceSource(
        endpoint="https://lf.example",
        data_policy="permitted",
        credentials={"public_key": _PUBLIC_KEY_ENV, "secret_key": _SECRET_KEY_ENV},
    )
    read = source.read()
    assert read.diagnostics == []
    assert len(read.units) == 1
    assert calls["init"]["public_key"] == public_value  # explicit, not ambient
    assert calls["init"]["secret_key"] == secret_value


@pytest.mark.live_lane
def test_real_langfuse_pull_smoke() -> None:
    """Opt-in real Langfuse pull (EG-R1-6) — uses the DEFAULT fetch (the lazy real SDK client).

    Double-guarded: skipped unless ``EVALGLASS_LIVE_LANES=1`` (collection hook) and an
    ``EVALGLASS_LANGFUSE_ENDPOINT`` is configured; it must be run in an egress-permitted live
    environment (the autouse hermetic socket guard blocks external connects in the required tier).
    Never required for ordinary CI.

    Asserts the pull actually SUCCEEDED — no diagnostics and at least one normalized unit — so a
    blocked socket, bad endpoint, or missing credentials (which ``read()`` converts to diagnostics
    + empty units) fails the test instead of greening over a pull that never happened.
    """
    endpoint = os.environ.get("EVALGLASS_LANGFUSE_ENDPOINT")
    if not endpoint:
        pytest.skip("no EVALGLASS_LANGFUSE_ENDPOINT — opt-in live Langfuse pull")
    source = LangfuseTraceSource(
        endpoint=endpoint,
        data_policy="permitted",
        credentials={"public_key": "LANGFUSE_PUBLIC_KEY", "secret_key": "LANGFUSE_SECRET_KEY"},
    )
    read = source.read()  # real SDK pull (lazy import); MissingPrerequisite if the extra is absent
    assert read.diagnostics == [], f"live Langfuse pull reported diagnostics: {read.diagnostics}"
    assert read.units, "live Langfuse pull returned no units — not a real exercise"
    check_envelopes_no_vendor_leak([u.envelope for u in read.units], forbidden_keys=_WRAPPER_KEYS)
