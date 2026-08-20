"""Hermetic Phoenix connector contract (EG-R2; ADR 0035).

Proves the Phoenix :class:`~evalglass.harness.ports.TraceSource` over the local fixture family
(``fixtures/connectors/phoenix.json``) — no ``arize-phoenix-client`` SDK, no socket. The live SDK
call is injected as ``fetch``; here it returns fixture payloads so the mapping, the egress gate, and
the fail-closed paths are all exercised hermetically. The real-pull path is ``live_lane`` (EG-R2-6).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters.trace_phoenix import PhoenixTraceSource
from evalglass.harness.lanes import MissingPrerequisite, built_in_lanes
from evalglass.harness.ports import TraceRead, TraceUnit
from tests.egts.checkers import check_envelopes_no_vendor_leak

_FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "connectors" / "phoenix.json").read_text(
        encoding="utf-8"
    )
)
_WRAPPER_KEYS = _FIXTURE["vendor_wrapper_keys"]


def _source(fetch: Any, *, data_policy: str = "permitted") -> PhoenixTraceSource:
    # Flattened options exactly as the runner seam passes them: factory(data_policy=..., **options).
    return PhoenixTraceSource(endpoint="https://px.example", data_policy=data_policy, fetch=fetch)


def _as_expected(unit: TraceUnit) -> dict[str, Any]:
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


def test_vendor_wrapper_payload_drops_vendor_objects() -> None:
    read = _source(lambda: _FIXTURE["vendor_wrapper"]).read()
    assert read.diagnostics == []
    assert [_as_expected(u) for u in read.units] == _FIXTURE["expected"]
    check_envelopes_no_vendor_leak([u.envelope for u in read.units], forbidden_keys=_WRAPPER_KEYS)


def test_envelope_carries_connector_uniform_fields() -> None:
    env = _source(lambda: _FIXTURE["good"]).read().units[0].envelope
    assert env.source == "phoenix-trace"
    assert env.data_policy.value == "permitted"
    assert env.provenance == {"trace": "phoenix-trace", "provider": "phoenix"}


def test_missing_endpoint_is_missing_prerequisite_skip() -> None:
    with pytest.raises(MissingPrerequisite):
        PhoenixTraceSource(data_policy="permitted", fetch=lambda: _FIXTURE["good"])


def test_lane_factory_is_runner_compatible() -> None:
    """The runner seam calls ``factory(root=root, data_policy=..., **opts)`` (flattened);
    construction must succeed, and with no SDK installed the default fetch is a clean skip."""
    factory = built_in_lanes().resolve("phoenix-trace")
    source = factory(root=Path("."), data_policy="permitted", endpoint="https://px.example")
    with pytest.raises(MissingPrerequisite):
        source.read()


@pytest.mark.parametrize("policy", ["forbidden", "missing", "unknown"])
def test_forbidden_policy_refuses_before_any_fetch(policy: str) -> None:
    calls: list[int] = []

    def spy() -> Any:
        calls.append(1)
        return _FIXTURE["good"]

    read = _source(spy, data_policy=policy).read()
    assert calls == [], "egress-before-effects: a non-egress policy must not call the provider"
    assert read.units == []
    assert read.diagnostics[0].code == "phoenix_egress_forbidden"


def test_malformed_response_is_a_diagnostic() -> None:
    read = _source(lambda: {"unexpected": "shape"}).read()
    assert read.units == []
    assert read.diagnostics[0].code == "phoenix_malformed_response"


def test_fetch_failure_is_a_diagnostic_not_a_crash() -> None:
    def boom() -> Any:
        raise RuntimeError("provider down")

    read = _source(boom).read()
    assert read.units == []
    assert read.diagnostics[0].code == "phoenix_malformed_response"


def test_missing_field_span_is_a_diagnostic() -> None:
    read = _source(lambda: _FIXTURE["missing_field"]).read()
    assert read.units == []  # span has no LLM output → mapping-incomplete diagnostic
    assert read.diagnostics


def test_malformed_span_surfaces_a_diagnostic_not_silent_empty() -> None:
    """A non-object span must surface a diagnostic, not silently vanish into an empty clean read."""
    read = _source(lambda: {"spans": ["not-an-object"]}).read()
    assert read.units == []
    assert read.diagnostics


def test_empty_payload_yields_no_units_no_diagnostics() -> None:
    read = _source(lambda: _FIXTURE["empty"]).read()
    assert isinstance(read, TraceRead)
    assert read.units == []
    assert read.diagnostics == []


#: A host-owned env-var NAME (a reference, not a secret); referenced rather than inlined next to the
#: api_key credential key so the secret scanner does not misread it (S6418 false positive).
_API_KEY_ENV = "PHOENIX_API_KEY"


def _install_fake_phoenix(
    monkeypatch: pytest.MonkeyPatch, *, spans: Any, calls: dict[str, Any]
) -> None:
    """Inject a fake ``phoenix.client`` module so the DEFAULT fetch path runs with no SDK/socket.
    The fake ``Client`` records its construction kwargs so a test can prove auth is passed
    explicitly (api_key always present — ``None`` when undeclared — no ambient fallback)."""
    import sys
    import types

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            calls["init"] = kwargs
            self.spans = types.SimpleNamespace(get_spans=lambda **_kw: spans)

    monkeypatch.setitem(sys.modules, "phoenix.client", types.SimpleNamespace(Client=_FakeClient))


def test_default_fetch_keyless_local_passes_api_key_none_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phoenix supports a credentialless local collector (ADR 0035): with no api_key declared the
    default fetch still pulls (no MissingPrerequisite), but passes ``api_key=None`` EXPLICITLY so
    the SDK cannot fall back to an ambient PHOENIX_API_KEY the lane never declared."""
    monkeypatch.delenv(_API_KEY_ENV, raising=False)
    calls: dict[str, Any] = {}
    _install_fake_phoenix(monkeypatch, spans=_FIXTURE["good"]["spans"], calls=calls)
    source = PhoenixTraceSource(endpoint="https://px.example", data_policy="permitted")
    read = source.read()
    assert read.diagnostics == []
    assert len(read.units) == 1
    assert "api_key" in calls["init"]  # passed explicitly, not omitted
    assert calls["init"]["api_key"] is None  # keyless-local; no ambient fallback


def test_default_fetch_declared_but_unresolved_api_key_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DECLARED api_key whose env var is unset is a misconfiguration → clean MissingPrerequisite
    skip before any client call, never a silent downgrade to an unauthenticated keyless pull."""
    monkeypatch.delenv(_API_KEY_ENV, raising=False)
    calls: dict[str, Any] = {}
    _install_fake_phoenix(monkeypatch, spans=_FIXTURE["good"]["spans"], calls=calls)
    source = PhoenixTraceSource(
        endpoint="https://px.example",
        data_policy="permitted",
        credentials={"api_key": _API_KEY_ENV},
    )
    with pytest.raises(MissingPrerequisite):
        source.read()
    assert calls == {}, "a declared-but-unresolved credential must not construct a keyless client"


def test_default_fetch_forwards_declared_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the lane declares an api_key credential, the default fetch forwards the resolved value
    explicitly to the client."""
    monkeypatch.setenv(_API_KEY_ENV, "px-resolved")
    calls: dict[str, Any] = {}
    _install_fake_phoenix(monkeypatch, spans=_FIXTURE["good"]["spans"], calls=calls)
    source = PhoenixTraceSource(
        endpoint="https://px.example",
        data_policy="permitted",
        credentials={"api_key": _API_KEY_ENV},
    )
    read = source.read()
    assert read.diagnostics == []
    assert len(read.units) == 1
    assert calls["init"]["api_key"] == "px-resolved"  # declared ref resolved + forwarded explicitly


@pytest.mark.live_lane
def test_real_phoenix_pull_smoke() -> None:
    """Opt-in real Phoenix pull (EG-R2-6) — DEFAULT fetch (lazy arize-phoenix-client).

    Double-guarded by ``EVALGLASS_LIVE_LANES=1`` + ``EVALGLASS_PHOENIX_ENDPOINT``; run only in an
    egress-permitted live environment. Asserts the pull SUCCEEDED (no diagnostics + at least one
    unit) so a blocked/failed pull fails rather than greening over a pull that never happened."""
    endpoint = os.environ.get("EVALGLASS_PHOENIX_ENDPOINT")
    if not endpoint:
        pytest.skip("no EVALGLASS_PHOENIX_ENDPOINT — opt-in live Phoenix pull")
    source = PhoenixTraceSource(
        endpoint=endpoint, data_policy="permitted", credentials={"api_key": "PHOENIX_API_KEY"}
    )
    read = source.read()
    assert read.diagnostics == [], f"live Phoenix pull reported diagnostics: {read.diagnostics}"
    assert read.units, "live Phoenix pull returned no units — not a real exercise"
    check_envelopes_no_vendor_leak([u.envelope for u in read.units], forbidden_keys=_WRAPPER_KEYS)
