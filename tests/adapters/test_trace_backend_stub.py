"""Layer-1 unit tests for the trace-backend stub lane (EG-M5-3; ADR 0018)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.trace_backend_stub import StubBackendTraceSource
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceSource


def _backend(tmp_path: Path, payload: object) -> StubBackendTraceSource:
    (tmp_path / "be.json").write_text(json.dumps(payload), encoding="utf-8")
    return StubBackendTraceSource(backend_path="be.json", root=tmp_path, query="project=x")


def test_no_backend_configured_skips() -> None:
    with pytest.raises(MissingPrerequisite):
        StubBackendTraceSource(backend_path=None, root=Path("."))


def test_maps_spans_and_drops_vendor_wrapper(tmp_path: Path) -> None:
    payload = {
        "_backend_internal": {"cursor": "opaque-vendor-object"},
        "project_id": "vendor-123",
        "spans": [
            {"trace_id": "t1", "attributes": {"output.value": "hi", "llm.model_name": "m"}},
        ],
    }
    read = _backend(tmp_path, payload).read()
    assert read.diagnostics == []
    env = read.units[0].envelope
    assert env.behavior["output"] == "hi"
    assert env.source == "trace-backend-stub"
    # No vendor wrapper crosses the boundary.
    for section in (env.behavior, env.metadata, env.provenance):
        assert "_backend_internal" not in section
        assert "project_id" not in section


def test_unavailable_backend_is_diagnostic(tmp_path: Path) -> None:
    src = StubBackendTraceSource(backend_path="missing.json", root=tmp_path)
    read = src.read()
    assert read.units == []
    assert read.diagnostics[0].code == "backend_unavailable"


def test_malformed_backend_is_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "be.json").write_text("{not json", encoding="utf-8")
    read = StubBackendTraceSource(backend_path="be.json", root=tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "backend_malformed_response"


def test_response_without_spans_is_diagnostic(tmp_path: Path) -> None:
    read = _backend(tmp_path, {"no": "spans"}).read()
    assert read.units == []
    assert read.diagnostics[0].code == "backend_malformed_response"


def test_span_missing_output_is_incomplete_not_a_score(tmp_path: Path) -> None:
    read = _backend(tmp_path, {"spans": [{"trace_id": "t1", "attributes": {}}]}).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_mapping_incomplete"


def test_satisfies_tracesource_protocol(tmp_path: Path) -> None:
    src = _backend(tmp_path, {"spans": []})
    assert isinstance(src, TraceSource)
    assert isinstance(src.read(), TraceRead)
