"""Hermetic LangSmith connector contract (EG-R3; ADR 0036).

Proves the LangSmith :class:`~evalglass.harness.ports.TraceSource` over the local fixture family
(``fixtures/connectors/langsmith.json``) — no ``langsmith`` SDK, no socket. The live SDK call is
injected as ``fetch``; here it returns fixture payloads so the run/span mapping, the egress gate,
and the fail-closed paths are all exercised hermetically. The real-pull path is ``live_lane``
(EG-R3-6). The lane-factory runner-compatibility test lands with lane registration (EG-R3-1, Slice
2); this slice ships the adapter + its hermetic proof.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters.trace_langsmith import LangSmithTraceSource
from evalglass.harness.lanes import MissingPrerequisite, built_in_lanes
from evalglass.harness.ports import TraceRead, TraceUnit
from tests.egts.checkers import check_envelopes_no_vendor_leak

_FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "connectors" / "langsmith.json").read_text(
        encoding="utf-8"
    )
)
_WRAPPER_KEYS = _FIXTURE["vendor_wrapper_keys"]

#: Host-owned environment-variable NAMES the lane resolves at run time — never secrets (the
#: connector boundary's ``parse_provider_options`` rejects literal secret values via a name regex).
#: Referenced rather than inlined next to the ``api_key`` credential key so the secret scanner does
#: not misread the mapping as a hard-coded key (S6418 false positive on an env-var reference).
_KEY_ENV, _WORKSPACE_ENV = "LANGSMITH_API_KEY", "LANGSMITH_WORKSPACE_ID"


def _source(fetch: Any, *, data_policy: str = "permitted") -> LangSmithTraceSource:
    # Flattened options exactly as the runner seam passes them: factory(data_policy=..., **options).
    return LangSmithTraceSource(
        endpoint="https://api.smith.example", data_policy=data_policy, fetch=fetch
    )


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
    assert env.source == "langsmith-trace"
    assert env.data_policy.value == "permitted"
    assert env.provenance == {"trace": "langsmith-trace", "provider": "langsmith"}


def test_missing_endpoint_is_missing_prerequisite_skip() -> None:
    with pytest.raises(MissingPrerequisite):
        LangSmithTraceSource(data_policy="permitted", fetch=lambda: _FIXTURE["good"])


def test_lane_factory_is_runner_compatible() -> None:
    """The runner seam calls ``factory(root=root, data_policy=..., **opts)`` (flattened);
    construction must succeed, and with no SDK installed the default fetch is a clean skip."""
    factory = built_in_lanes().resolve("langsmith-trace")
    source = factory(root=Path("."), data_policy="permitted", endpoint="https://api.smith.example")
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
    assert read.diagnostics[0].code == "langsmith_egress_forbidden"


def test_malformed_response_is_a_diagnostic() -> None:
    read = _source(lambda: {"unexpected": "shape"}).read()
    assert read.units == []
    assert read.diagnostics[0].code == "langsmith_malformed_response"


def test_fetch_failure_is_a_diagnostic_not_a_crash() -> None:
    def boom() -> Any:
        raise RuntimeError("provider down")

    read = _source(boom).read()
    assert read.units == []
    assert read.diagnostics[0].code == "langsmith_malformed_response"


def test_missing_field_run_is_a_diagnostic() -> None:
    read = _source(lambda: _FIXTURE["missing_field"]).read()
    assert read.units == []  # run has no outputs → no LLM output → mapping-incomplete diagnostic
    assert read.diagnostics


def test_malformed_run_surfaces_a_diagnostic_not_silent_empty() -> None:
    """A non-object run must surface a diagnostic, not silently vanish into an empty clean read."""
    read = _source(lambda: {"runs": ["not-an-object"]}).read()
    assert read.units == []
    assert read.diagnostics


def test_empty_payload_yields_no_units_no_diagnostics() -> None:
    read = _source(lambda: _FIXTURE["empty"]).read()
    assert isinstance(read, TraceRead)
    assert read.units == []
    assert read.diagnostics == []


def test_uuid_run_ids_are_coerced_to_strings() -> None:
    """Regression: the live SDK returns ``UUID`` ids, but ``map_span`` resolves only string ids.

    Without coercion every live run would map incomplete (zero units) while the string-id fixture
    passes. A non-string id must be stringified so the run still maps to a unit.
    """
    import uuid

    run_uuid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    trace_uuid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    payload = {
        "runs": [
            {
                "id": run_uuid,
                "trace_id": trace_uuid,
                "run_type": "llm",
                "inputs": {"input": "q"},
                "outputs": {"output": "a"},
            }
        ]
    }
    read = _source(lambda: payload).read()
    assert read.diagnostics == []
    assert len(read.units) == 1
    assert read.units[0].unit.unit_id == str(run_uuid)
    assert read.units[0].unit.trace_id == str(trace_uuid)


def _install_fake_langsmith(
    monkeypatch: pytest.MonkeyPatch, *, runs: list[Any], calls: dict[str, Any]
) -> None:
    """Inject a fake ``langsmith`` module so the DEFAULT fetch path is exercised with no SDK/socket.

    The fake ``Client`` records its construction kwargs and ``list_runs`` kwargs so a test can prove
    credentials are passed explicitly (no ambient pickup) and host-declared filters are forwarded.
    """
    import sys
    import types

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            calls["init"] = kwargs

        def list_runs(self, **kwargs: Any) -> list[Any]:
            calls["list_runs"] = kwargs
            return runs

    monkeypatch.setitem(sys.modules, "langsmith", types.SimpleNamespace(Client=_FakeClient))


def test_default_fetch_requires_credentials_before_any_client_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permitted, endpoint-only config (no credentials) is a clean MissingPrerequisite skip — the
    declared API-credentials prerequisite is enforced BEFORE any client construction or list_runs
    call, so a missing key never becomes a keyless/ambient-credential provider pull."""
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    calls: dict[str, Any] = {}
    _install_fake_langsmith(monkeypatch, runs=[], calls=calls)
    source = LangSmithTraceSource(endpoint="https://api.smith.example", data_policy="permitted")
    with pytest.raises(MissingPrerequisite):
        source.read()
    assert calls == {}, "no client was constructed and no list_runs call was made"


def test_default_fetch_passes_explicit_credentials_and_forwards_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default fetch passes the resolved key explicitly (blocking ambient SDK env pickup) and
    forwards the host-declared evidence scope (project/limit/start_time/query) to ``list_runs``."""
    monkeypatch.setenv(_KEY_ENV, "resolved-langsmith-token")
    monkeypatch.setenv(_WORKSPACE_ENV, "ws-test")
    calls: dict[str, Any] = {}
    run = {
        "id": "run-9",
        "trace_id": "tr-9",
        "run_type": "llm",
        "inputs": {"input": "q"},
        "outputs": {"output": "a"},
        "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-01T00:00:01Z",
        "extra": {"metadata": {"ls_model_name": "m"}},
    }
    _install_fake_langsmith(monkeypatch, runs=[run], calls=calls)
    source = LangSmithTraceSource(
        endpoint="https://api.smith.example",
        data_policy="permitted",
        project="p1",
        limit=5,
        start_time="2026-01-01",
        query="run_type:llm",
        credentials={"api_key": _KEY_ENV, "workspace_id": _WORKSPACE_ENV},
    )
    read = source.read()
    assert read.diagnostics == []
    assert len(read.units) == 1
    assert calls["init"]["api_key"] == "resolved-langsmith-token"  # explicit, not ambient
    # ALL declared credentials forwarded explicitly (org-scoped keys need workspace_id) — never
    # dropped to an ambient fallback, which would defeat the explicit-credential boundary.
    assert calls["init"]["workspace_id"] == "ws-test"
    assert calls["list_runs"]["project_name"] == "p1"
    assert calls["list_runs"]["limit"] == 5
    assert calls["list_runs"]["start_time"] == "2026-01-01"  # declared time window honored
    assert calls["list_runs"]["filter"] == "run_type:llm"  # declared query honored


@pytest.mark.live_lane
def test_real_langsmith_pull_smoke() -> None:
    """Opt-in real LangSmith pull (EG-R3-6) — DEFAULT fetch (lazy ``langsmith`` SDK).

    Double-guarded by ``EVALGLASS_LIVE_LANES=1`` + ``EVALGLASS_LANGSMITH_ENDPOINT``; run only in an
    egress-permitted live environment. Asserts the pull SUCCEEDED (no diagnostics + at least one
    unit) so a blocked/failed pull fails rather than greening over a pull that never happened."""
    endpoint = os.environ.get("EVALGLASS_LANGSMITH_ENDPOINT")
    if not endpoint:
        pytest.skip("no EVALGLASS_LANGSMITH_ENDPOINT — opt-in live LangSmith pull")
    source = LangSmithTraceSource(
        endpoint=endpoint,
        data_policy="permitted",
        credentials={"api_key": _KEY_ENV},
    )
    read = source.read()
    assert read.diagnostics == [], f"live LangSmith pull reported diagnostics: {read.diagnostics}"
    assert read.units, "live LangSmith pull returned no units — not a real exercise"
    check_envelopes_no_vendor_leak([u.envelope for u in read.units], forbidden_keys=_WRAPPER_KEYS)
