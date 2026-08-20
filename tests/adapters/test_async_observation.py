"""Layer-1 unit tests for the async-observation lane (EG-M5-5 S1c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters.async_observation import AsyncObservationTraceSource
from evalglass.core import TraceEnvelope
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceSource
from tests.async_recording_factory import write_async_recording

_SPANS: list[dict[str, Any]] = [
    {
        "trace_id": "t1",
        "span_id": "s1",
        "parent_span_id": None,
        "concurrent": True,
        "attributes": {"output.value": "a"},
    },
    {
        "trace_id": "t1",
        "span_id": "s2",
        "parent_span_id": "s1",
        "concurrent": True,
        "attributes": {"output.value": "b"},
    },
]


def _source(
    tmp_path: Path, spans: list[dict[str, Any]] | None = None
) -> AsyncObservationTraceSource:
    rec = write_async_recording(tmp_path, spans if spans is not None else _SPANS)
    return AsyncObservationTraceSource(recording_path=rec, root=tmp_path)


def test_no_recording_skips() -> None:
    with pytest.raises(MissingPrerequisite):
        AsyncObservationTraceSource(recording_path=None, root=Path("."))


def test_satisfies_tracesource_protocol(tmp_path: Path) -> None:
    src = _source(tmp_path)
    assert isinstance(src, TraceSource)
    assert isinstance(src.read(), TraceRead)


def test_observes_recorded_spans_into_envelopes(tmp_path: Path) -> None:
    read = _source(tmp_path).read()
    assert read.diagnostics == []
    assert [u.envelope.behavior["output"] for u in read.units] == ["a", "b"]
    # Async metadata is carried as recorded fact (not an orchestration handle).
    assert read.units[1].envelope.metadata["async"]["parent_span_id"] == "s1"
    assert read.units[0].envelope.source == "async-observation"


def test_unavailable_recording_is_diagnostic(tmp_path: Path) -> None:
    src = AsyncObservationTraceSource(recording_path="missing.json", root=tmp_path)
    read = src.read()
    assert read.units == []
    assert read.diagnostics[0].code == "async_recording_unavailable"


def test_malformed_recording_is_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "rec.json").write_text("{bad", encoding="utf-8")
    read = AsyncObservationTraceSource(recording_path="rec.json", root=tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "async_recording_malformed"


def test_no_raw_shape_in_envelope_behavior(tmp_path: Path) -> None:
    read = _source(tmp_path).read()
    for unit in read.units:
        assert not isinstance(unit.envelope.behavior["output"], TraceEnvelope)
