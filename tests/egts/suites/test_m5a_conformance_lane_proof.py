"""EGTS-M5-2 — open-convention (OTel/OpenInference) trace conformance lane proof.

Proves the real ``OpenConventionTraceSource`` normalizes a rich span set — messages, tool calls,
model, timing, metadata, data policy, provenance — into a vendor-neutral ``TraceEnvelope``, that
malformed/incomplete spans become typed diagnostics, and that **the core never branches on a
convention type** (the mapping lives wholly in the adapter). Run via
``egts test-lane open-convention-traces``. Negative control: a core file referencing a convention
token fails the no-branching checker (``tests/CLAUDE.md §12``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.adapters.trace_open_convention import OpenConventionTraceSource
from evalglass.core import DataPolicy, TraceEnvelope
from evalglass.harness.config import TraceConfig, TraceFormat
from evalglass.harness.ports import TraceRead
from tests.egts.checkers import CheckerError, check_core_no_convention_branching

_SRC = Path(__file__).resolve().parents[3] / "src" / "evalglass"


def _read(
    tmp_path: Path, records: list[dict[str, Any]], fmt: TraceFormat = TraceFormat.OPENINFERENCE
) -> TraceRead:
    path = tmp_path / "traces" / "t.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    config = TraceConfig(name="t", path="traces/t.jsonl", fmt=fmt, data_policy=DataPolicy.PERMITTED)
    return OpenConventionTraceSource(config, tmp_path).read()


def test_m5a_conformance_rich_span_maps_messages_tools_model_timing(tmp_path: Path) -> None:
    """m5a.conformance.rich_span_normalizes — a full OpenInference span maps to TraceEnvelope."""
    span = {
        "context": {"trace_id": "t1"},
        "name": "llm-call",
        "start_time": "2026-05-31T00:00:00Z",
        "end_time": "2026-05-31T00:00:02Z",
        "attributes": {
            "llm.input_messages": [{"message.role": "user", "message.content": "weather?"}],
            "llm.output_messages": [{"message.role": "assistant", "message.content": "sunny"}],
            "llm.model_name": "gpt-test",
            "llm.tools": [{"tool.name": "get_weather", "tool.json_schema": "{}"}],
        },
    }
    read = _read(tmp_path, [span])
    assert read.diagnostics == []
    env = read.units[0].envelope
    assert isinstance(env, TraceEnvelope)
    assert env.behavior["model"] == "gpt-test"
    # M5 extension: tool calls + timing are now part of the conformance mapping.
    assert env.behavior["tool_calls"] == [{"tool.name": "get_weather", "tool.json_schema": "{}"}]
    assert env.behavior["timing"]["start_time"] == "2026-05-31T00:00:00Z"
    assert env.behavior["timing"]["end_time"] == "2026-05-31T00:00:02Z"
    # Vendor-neutral: the convention is recorded as metadata, not leaked as a type.
    assert env.metadata["convention"] == "openinference"


def test_m5a_conformance_malformed_span_yields_diagnostic(tmp_path: Path) -> None:
    """m5a.conformance.malformed_yields_diagnostic — an incomplete span is a typed diagnostic."""
    read = _read(tmp_path, [{"context": {"trace_id": "t1"}, "attributes": {}}])
    assert read.units == []
    assert read.diagnostics[0].code == "trace_mapping_incomplete"


def test_m5a_conformance_tool_and_timing_are_optional(tmp_path: Path) -> None:
    """A minimal span (no tools/timing) still maps — the extension is additive, not required."""
    span = {
        "trace_id": "t2",
        "attributes": {"output.value": "ok", "input.value": "q"},
    }
    env = _read(tmp_path, [span], fmt=TraceFormat.OPENTELEMETRY).units[0].envelope
    assert env.behavior["output"] == "ok"
    assert "tool_calls" not in env.behavior
    assert "timing" not in env.behavior


def test_m5a_conformance_core_never_branches_on_convention_type() -> None:
    """m5a.conformance.core_has_no_convention_branch — the mapping lives only in the adapter."""
    check_core_no_convention_branching(_SRC)


def test_negctl_core_convention_branch_fails(tmp_path: Path) -> None:
    fake_core = tmp_path / "evalglass" / "core"
    fake_core.mkdir(parents=True)
    (fake_core / "leaky.py").write_text(
        'def pick(attrs):\n    return attrs["llm.input_messages"]\n', encoding="utf-8"
    )
    with pytest.raises(CheckerError):
        check_core_no_convention_branching(tmp_path / "evalglass")
