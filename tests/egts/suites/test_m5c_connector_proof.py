"""EGTS-M5C-6 — live trace-connector normalization proof (Route Proof, Trust Proof).

Proves the three real product connectors (EG-R1/R2/R3) over their local fixture families, with no
provider SDK and no socket (the live SDK call is injected as ``fetch``). One scenario per provider
backs the single EG-M5C-6 coverage row:

* ``m5c.trace.langfuse_normalization`` — Langfuse traces → vendor-neutral ``TraceEnvelope``;
* ``m5c.trace.phoenix_normalization`` — Phoenix spans → vendor-neutral ``TraceEnvelope``;
* ``m5c.trace.langsmith_normalization`` — LangSmith runs → vendor-neutral ``TraceEnvelope``.

Each scenario proves the route (provider payload → ``TraceEnvelope``/``EvalUnit`` matching the
declared ``expected``), the boundary (no vendor wrapper object crosses into the core-visible path),
the authority line (a connector ``TraceRead`` carries no score/verdict/authority/ci_should_fail —
it imports evidence, never authority), and opt-in deletability. A shared negative control proves the
vendor-leak checker actually fires on a seeded leak, so a real leak could not pass silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters._connector_boundary import BaseTraceConnector
from evalglass.adapters.trace_langfuse import LangfuseTraceSource
from evalglass.adapters.trace_langsmith import LangSmithTraceSource
from evalglass.adapters.trace_phoenix import PhoenixTraceSource
from evalglass.core import TraceEnvelope
from evalglass.harness.ports import TraceRead, TraceUnit
from tests.egts.checkers import CheckerError, check_envelopes_no_vendor_leak
from tests.egts.lane_conformance import assert_lane_is_opt_in_and_declared

_FIXTURES = Path(__file__).resolve().parents[1].parent / "adapters" / "fixtures" / "connectors"

#: provider -> (adapter class, lane name, scenario id, an endpoint for the flattened constructor).
_PROVIDERS: dict[str, tuple[type[BaseTraceConnector], str, str, str]] = {
    "langfuse": (LangfuseTraceSource, "langfuse-trace", "m5c.trace.langfuse_normalization", "h"),
    "phoenix": (PhoenixTraceSource, "phoenix-trace", "m5c.trace.phoenix_normalization", "px"),
    "langsmith": (
        LangSmithTraceSource,
        "langsmith-trace",
        "m5c.trace.langsmith_normalization",
        "s",
    ),
}


def _fixture(provider: str) -> dict[str, Any]:
    data = json.loads((_FIXTURES / f"{provider}.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


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


def _read(provider: str, variant: str) -> TraceRead:
    cls, _lane, _scenario, endpoint = _PROVIDERS[provider]
    payload = _fixture(provider)[variant]
    return cls(
        endpoint=f"https://{endpoint}.invalid", data_policy="permitted", fetch=lambda: payload
    ).read()


@pytest.mark.parametrize("provider", sorted(_PROVIDERS), ids=lambda p: _PROVIDERS[p][2])
def test_m5c_trace_normalization(provider: str) -> None:
    """m5c.trace.<provider>_normalization — the real connector normalizes a provider payload to the
    declared vendor-neutral TraceEnvelope/EvalUnit, with no vendor object crossing the boundary."""
    fixture = _fixture(provider)
    # Route: the good payload maps to exactly the declared expected normalized output.
    good = _read(provider, "good")
    assert good.diagnostics == []
    assert [_as_expected(u) for u in good.units] == fixture["expected"]
    # Boundary: a payload carrying vendor wrapper objects yields the same normalized output, and no
    # wrapper key crosses into a core-visible envelope section.
    wrapped = _read(provider, "vendor_wrapper")
    assert wrapped.diagnostics == []
    assert [_as_expected(u) for u in wrapped.units] == fixture["expected"]
    check_envelopes_no_vendor_leak(
        [u.envelope for u in wrapped.units], forbidden_keys=fixture["vendor_wrapper_keys"]
    )


@pytest.mark.parametrize("provider", sorted(_PROVIDERS), ids=lambda p: _PROVIDERS[p][2])
def test_m5c_trace_read_imports_evidence_never_authority(provider: str) -> None:
    """A connector yields input evidence only — a TraceRead has no score/verdict/authority surface,
    so a provider success can never strengthen the Scorecard claim (the EG-M5C-6 trust line)."""
    read = _read(provider, "good")
    assert isinstance(read, TraceRead)
    for forbidden in ("score", "scores", "verdict", "authority", "can_gate", "ci_should_fail"):
        assert not hasattr(read, forbidden), f"a connector read exposes {forbidden!r}"


@pytest.mark.parametrize("provider", sorted(_PROVIDERS), ids=lambda p: _PROVIDERS[p][2])
def test_m5c_connector_lane_is_opt_in_and_deletable(provider: str) -> None:
    """Each connector lane is declared, import-isolated, conservatively mature, and removable — the
    required hermetic tier imports no provider SDK, so deleting a connector changes no required
    run."""
    _cls, lane, _scenario, _endpoint = _PROVIDERS[provider]
    assert_lane_is_opt_in_and_declared(lane)


def test_negctl_vendor_leak_checker_fires_on_a_seeded_leak() -> None:
    """Negative control: the vendor-leak checker actually fails when a vendor-internal object is
    seeded into a TraceEnvelope — so a real leak past the boundary could not pass silently."""
    leaked = TraceEnvelope.from_dict(
        {
            "trace_id": "t1",
            "source": "phoenix-trace",
            "behavior": {"output": "a"},
            "data_policy": "permitted",
            "metadata": {"_phoenix_internal": {"exporter": "otlp"}},
            "provenance": {"trace": "phoenix-trace"},
        }
    )
    with pytest.raises(CheckerError):
        check_envelopes_no_vendor_leak([leaked], forbidden_keys=["_phoenix_internal"])
