"""Open-convention (OpenTelemetry / OpenInference) ``TraceSource`` adapter (EG-M1-3b).

Maps provider-shaped span records into the same vendor-neutral
:class:`~evalglass.core.TraceEnvelope` the local route produces, with **no** tracing-backend
SDK — it operates on static JSON dicts, keeping the required tier hermetic. The mapped
attribute subset is pinned in ADR 0006:

* trace id  — ``context.trace_id`` / ``trace_id`` / ``context.span_id`` / ``span_id``
* input     — ``llm.input_messages`` (OpenInference) / ``input.value`` / ``gen_ai.prompt``
* output    — ``llm.output_messages`` / ``output.value`` / ``gen_ai.completion``
* model     — ``llm.model_name`` / ``gen_ai.request.model``

EG-M5-2 (conformance lane; ADR 0006 extended) adds two **optional** mappings:

* tool calls — ``llm.tools`` / ``tool_calls`` / ``message.tool_calls`` / ``gen_ai.tool.calls``
* timing     — record-level ``start_time`` / ``end_time`` / ``duration_ms``

A record missing a required field (no id, no extractable output) yields a visible
``trace_mapping_incomplete`` diagnostic rather than a low score; the core only ever sees the
normalized ``TraceEnvelope`` (it never branches on a convention type — proven by the EGTS-M5-2
``check_core_no_convention_branching`` checker).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evalglass.adapters._jsonl import read_trace_jsonl
from evalglass.core import ContractError, Diagnostic, EvalUnit, Severity, TraceEnvelope, UnitKind
from evalglass.harness.config import TraceConfig
from evalglass.harness.ports import TraceRead, TraceUnit

_INPUT_KEYS = ("llm.input_messages", "input.value", "gen_ai.prompt")
_OUTPUT_KEYS = ("llm.output_messages", "output.value", "gen_ai.completion")
_MODEL_KEYS = ("llm.model_name", "gen_ai.request.model")
# EG-M5-2 conformance extension (ADR 0006 extended): tool calls + span timing. Both are optional —
# a span without them still maps; present, they are normalized into the vendor-neutral envelope.
_TOOL_KEYS = ("llm.tools", "tool_calls", "message.tool_calls", "gen_ai.tool.calls")
# Behavior-layer preservation (Epic B / B3): the raw model output the application parsed, and the
# parser's own diagnostics, kept DISTINCT from the application-visible ``output`` so a metric can
# measure the intended layer. Both are optional; when present they never replace ``output``.
_RAW_OUTPUT_KEYS = ("llm.output.raw", "raw_output.value", "output.raw.value")
_PARSER_DIAG_KEYS = ("evalglass.parser_diagnostics", "parser.diagnostics")


def _extract_timing(record: Mapping[str, Any]) -> dict[str, Any]:
    """Collect span timing (start/end/duration) from record-level fields, if present."""
    timing: dict[str, Any] = {}
    for key in ("start_time", "end_time", "duration_ms"):
        value = record.get(key)
        if isinstance(value, str | int | float) and not isinstance(value, bool):
            timing[key] = value
    return timing


def _first_present(attributes: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in attributes:
            return attributes[key]
    return None


class OpenConventionTraceSource:
    """A :class:`~evalglass.harness.ports.TraceSource` for OTel/OpenInference-shaped JSONL."""

    def __init__(self, config: TraceConfig, root: Path) -> None:
        self._config = config
        self._root = root

    def read(self) -> TraceRead:
        return read_trace_jsonl(self._config, self._root, self._map, adapter="open_convention")

    def _map(self, record: Any, lineno: int, loc: str) -> TraceUnit | Diagnostic:
        def invalid(message: str) -> Diagnostic:
            return Diagnostic(
                code="trace_invalid_record", severity=Severity.ERROR, message=message, location=loc
            )

        def incomplete(message: str) -> Diagnostic:
            return Diagnostic(
                code="trace_mapping_incomplete",
                severity=Severity.ERROR,
                message=message,
                location=loc,
            )

        if not isinstance(record, Mapping):
            return invalid(f"trace record must be a JSON object, got {type(record).__name__}")
        attributes = record.get("attributes", {})
        if not isinstance(attributes, Mapping):
            return invalid("span 'attributes' must be an object")

        trace_id = self._resolve_id(record)
        if trace_id is None:
            return incomplete("span has no resolvable trace/span id")
        output = _first_present(attributes, _OUTPUT_KEYS)
        # Behavior-layer preservation (B3): raw model output and parser diagnostics are distinct
        # from the application ``output`` and never replace it. A parser-rejected span (raw output
        # present, application output absent) is evidence, not a dropped record.
        raw_output = _first_present(attributes, _RAW_OUTPUT_KEYS)
        parser_diags = _first_present(attributes, _PARSER_DIAG_KEYS)
        if output is None and raw_output is None and parser_diags is None:
            return incomplete(
                "span has no LLM output (expected one of: " + ", ".join(_OUTPUT_KEYS) + ")"
            )

        behavior: dict[str, Any] = {}
        if output is not None:
            behavior["output"] = output
        if raw_output is not None:
            behavior["raw_output"] = raw_output
        if parser_diags is not None:
            behavior["parser_diagnostics"] = parser_diags
        input_value = _first_present(attributes, _INPUT_KEYS)
        if input_value is not None:
            behavior["input"] = input_value
        model = _first_present(attributes, _MODEL_KEYS)
        if model is not None:
            behavior["model"] = model
        tool_calls = _first_present(attributes, _TOOL_KEYS)
        if tool_calls is not None:
            behavior["tool_calls"] = tool_calls
        timing = _extract_timing(record)
        if timing:
            behavior["timing"] = timing

        metadata: dict[str, Any] = {"convention": self._config.fmt.value}
        if isinstance(record.get("name"), str):
            metadata["span_name"] = record["name"]

        envelope_data = {
            "trace_id": trace_id,
            "source": self._config.fmt.value,
            "behavior": behavior,
            "data_policy": self._config.data_policy.value,
            "metadata": metadata,
            "provenance": {
                "trace": self._config.name,
                "line": lineno,
                "convention": self._config.fmt.value,
            },
        }
        try:
            envelope = TraceEnvelope.from_dict(envelope_data)
        except ContractError as exc:  # defensive: behavior/trace_id are already validated above
            return invalid(str(exc))
        return TraceUnit(
            envelope=envelope,
            unit=EvalUnit(
                unit_id=f"{self._config.name}#{lineno}", kind=UnitKind.CALL, trace_id=trace_id
            ),
        )

    @staticmethod
    def _resolve_id(record: Mapping[str, Any]) -> str | None:
        context = record.get("context")
        ctx = context if isinstance(context, Mapping) else {}
        for candidate in (
            ctx.get("trace_id"),
            record.get("trace_id"),
            ctx.get("span_id"),
            record.get("span_id"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None
