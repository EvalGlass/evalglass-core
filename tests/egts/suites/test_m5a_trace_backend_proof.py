"""EGTS-M5-3 — trace backend (stub) lane proof (Integration Proof).

Proves the real ``StubBackendTraceSource``: it yields **only** ``TraceEnvelope`` records (no vendor
object crosses the boundary into core/evaluator/RunRecord/Scorecard), backend
unavailable/malformed is a typed diagnostic separate from any score, the lane is declared +
import-isolated (deletable), and a missing backend skips. Run via ``egts test-lane trace-backend``.
Negative controls per checker (``tests/CLAUDE.md §12``).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evalglass.adapters.trace_backend_stub import StubBackendTraceSource
from evalglass.harness.lanes import built_in_lanes
from evalglass.harness.ports import TraceRead
from tests.egts.checkers import (
    CheckerError,
    check_envelopes_no_vendor_leak,
    check_lane_imports_isolated,
    check_lane_metadata,
)

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"
_VENDOR_KEYS = ("_backend_internal", "project_id", "raw_span")


def _read(tmp_path: Path, payload: object) -> TraceRead:
    (tmp_path / "be.json").write_text(json.dumps(payload), encoding="utf-8")
    return StubBackendTraceSource(backend_path="be.json", root=tmp_path, query="q").read()


def test_m5a_trace_backend_yields_only_normalized_envelopes(tmp_path: Path) -> None:
    """m5a.trace_backend.no_vendor_object_past_boundary — vendor wrapper never reaches an env."""
    payload = {
        "_backend_internal": {"cursor": "opaque"},
        "project_id": "vendor-123",
        "spans": [{"trace_id": "t1", "attributes": {"output.value": "hi"}}],
    }
    read = _read(tmp_path, payload)
    assert read.diagnostics == []
    envelopes = [u.envelope for u in read.units]
    check_envelopes_no_vendor_leak(envelopes, forbidden_keys=_VENDOR_KEYS)


def test_negctl_vendor_leak_fails() -> None:
    leaky = SimpleNamespace(
        behavior={"output": "x", "_backend_internal": {"cursor": "opaque"}},
        metadata={},
        provenance={},
    )
    with pytest.raises(CheckerError):
        check_envelopes_no_vendor_leak([leaky], forbidden_keys=_VENDOR_KEYS)


def test_m5a_trace_backend_unavailable_is_diagnostic(tmp_path: Path) -> None:
    """m5a.trace_backend.unavailable_is_diagnostic — backend down → diagnostic, not a score."""
    read = StubBackendTraceSource(backend_path="missing.json", root=tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "backend_unavailable"


def test_m5a_trace_backend_malformed_is_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "be.json").write_text("{bad", encoding="utf-8")
    read = StubBackendTraceSource(backend_path="be.json", root=tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "backend_malformed_response"


def test_m5a_trace_backend_lane_is_declared_and_isolated() -> None:
    """m5a.trace_backend.declared_and_deletable — declared metadata + no required import of lane."""
    lane = built_in_lanes().get("trace-backend")
    check_lane_metadata(lane)
    check_lane_imports_isolated(_SRC, lane.module)


def test_m5a_trace_backend_resolves_via_registry() -> None:
    factory = built_in_lanes().resolve("trace-backend")
    assert factory is StubBackendTraceSource
