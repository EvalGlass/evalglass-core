"""Open-convention (OpenTelemetry / OpenInference) trace mapping (EG-M1-3b).

Maps static, provider-shaped span records into the same vendor-neutral ``TraceEnvelope`` the
local route produces — with **no** tracing-backend SDK (required tier is hermetic). Missing
required fields produce a visible mapping diagnostic, never a low score. The mapped subset is
pinned in ADR 0006.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.trace_open_convention import OpenConventionTraceSource
from evalglass.core import TraceEnvelope, UnitKind
from evalglass.harness.config import TraceConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.ports import TraceSource


def _write(tmp_path: Path, lines: list[str]) -> None:
    (tmp_path / "t.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _source(tmp_path: Path, fmt: str = "openinference") -> OpenConventionTraceSource:
    cfg = TraceConfig.from_mapping(
        {"path": "t.jsonl", "format": fmt, "data_policy": "permitted"}, 0
    )
    return OpenConventionTraceSource(cfg, root=tmp_path)


def test_openinference_messages_map_to_envelope(tmp_path: Path) -> None:
    span = {
        "context": {"trace_id": "abc123"},
        "name": "llm.chat",
        "attributes": {
            "openinference.span.kind": "LLM",
            "llm.input_messages": [{"message.role": "user", "message.content": "2+2?"}],
            "llm.output_messages": [{"message.role": "assistant", "message.content": "4"}],
            "llm.model_name": "gpt-test",
        },
    }
    _write(tmp_path, [json.dumps(span)])
    read = _source(tmp_path, "openinference").read()
    assert read.diagnostics == []
    tu = read.units[0]
    assert isinstance(tu.envelope, TraceEnvelope)
    assert tu.envelope.trace_id == "abc123"
    assert tu.envelope.source == "openinference"
    assert tu.envelope.behavior["input"] == [{"message.role": "user", "message.content": "2+2?"}]
    assert tu.envelope.behavior["output"] == [{"message.role": "assistant", "message.content": "4"}]
    assert tu.envelope.behavior["model"] == "gpt-test"
    assert tu.unit.kind is UnitKind.CALL
    assert tu.unit.trace_id == "abc123"


def test_generic_input_output_value_map(tmp_path: Path) -> None:
    span = {"trace_id": "t1", "attributes": {"input.value": "q", "output.value": "a"}}
    _write(tmp_path, [json.dumps(span)])
    env = _source(tmp_path).read().units[0].envelope
    assert env.behavior["input"] == "q"
    assert env.behavior["output"] == "a"


def test_otel_gen_ai_attributes_map(tmp_path: Path) -> None:
    span = {
        "span_id": "s1",
        "attributes": {
            "gen_ai.prompt": "hello",
            "gen_ai.completion": "hi",
            "gen_ai.request.model": "m-1",
        },
    }
    _write(tmp_path, [json.dumps(span)])
    env = _source(tmp_path, "opentelemetry").read().units[0].envelope
    assert env.source == "opentelemetry"
    assert env.behavior["output"] == "hi"
    assert env.behavior["model"] == "m-1"


def test_missing_output_yields_mapping_diagnostic(tmp_path: Path) -> None:
    span = {"trace_id": "t1", "attributes": {"input.value": "q"}}  # no output anywhere
    _write(tmp_path, [json.dumps(span)])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_mapping_incomplete"


def test_missing_trace_id_yields_mapping_diagnostic(tmp_path: Path) -> None:
    span = {"attributes": {"input.value": "q", "output.value": "a"}}
    _write(tmp_path, [json.dumps(span)])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_mapping_incomplete"


def test_attributes_not_object_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "attributes": [1, 2]})])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_invalid_record"


def test_non_mapping_record_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps([1, 2, 3])])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_invalid_record"


def test_malformed_json_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, ["{ not json"])
    read = _source(tmp_path).read()
    assert read.diagnostics[0].code == "trace_invalid_json"


def test_missing_file_is_setup_error(tmp_path: Path) -> None:
    cfg = TraceConfig.from_mapping({"path": "nope.jsonl", "format": "openinference"}, 0)
    with pytest.raises(SetupError) as exc:
        OpenConventionTraceSource(cfg, root=tmp_path).read()
    assert exc.value.diagnostic.code == "trace_not_found"


def test_adapter_satisfies_tracesource_protocol(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "attributes": {"output.value": "a"}})])
    assert isinstance(_source(tmp_path), TraceSource)


def test_no_tracing_sdk_imported() -> None:
    # Hermetic required tier: the mapper works on static dicts and must not import a
    # tracing backend SDK (EGTS-M1-4 negative control).
    import evalglass.adapters.trace_open_convention as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "import opentelemetry" not in source
    assert "import openinference" not in source


def test_openinference_json_values_are_parsed_to_objects() -> None:
    """A JSON-mime output.value (Phoenix/LangSmith/OTel) becomes a mapping, not a string —
    so a host evaluator that expects structured output reads it (regression: was non-evaluable)."""
    from evalglass.adapters._span_mapping import behavior_from_attributes

    behavior = behavior_from_attributes(
        {
            "output.value": '{"entities": [{"classification": "class-a"}]}',
            "output.mime_type": "application/json",
            "input.value": "input evidence",
        }
    )
    assert behavior is not None
    assert isinstance(behavior["output"], dict)
    assert behavior["output"]["entities"][0]["classification"] == "class-a"
    assert behavior["input"] == "input evidence"  # plain text stays a string


def test_openinference_plaintext_output_stays_a_string() -> None:
    from evalglass.adapters._span_mapping import behavior_from_attributes

    behavior = behavior_from_attributes({"output.value": "Paris", "input.value": "capital?"})
    assert behavior is not None
    assert behavior["output"] == "Paris"  # not JSON → unchanged, never a crash
