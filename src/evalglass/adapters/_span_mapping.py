"""Shared open-convention span reading/mapping for optional trace lanes (EG-M5).

The trace-backend stub and async-observation lanes both read a ``{"spans": [...]}`` recording and
normalize each open-convention span into a vendor-neutral :class:`~evalglass.core.TraceEnvelope`.
This module holds the whole shared flow — file read, span loop, id resolution, behavior assembly,
envelope construction — so the lanes stay thin and DRY; each lane supplies only what differs
(``source``, per-span ``metadata``, ``provenance``, diagnostic codes, optional timing).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from evalglass.adapters._jsonl import _reject_constant
from evalglass.adapters.trace_open_convention import (
    _INPUT_KEYS,
    _MODEL_KEYS,
    _OUTPUT_KEYS,
    _PARSER_DIAG_KEYS,
    _RAW_OUTPUT_KEYS,
    _TOOL_KEYS,
    _extract_timing,
    _first_present,
)
from evalglass.core import (
    ContractError,
    DataPolicy,
    Diagnostic,
    EvalUnit,
    Severity,
    TraceEnvelope,
    UnitKind,
)
from evalglass.harness.ports import TraceRead, TraceUnit


def policy_or_unknown(value: str) -> DataPolicy:
    """Coerce a host policy string to ``DataPolicy``; an unknown value fails safe to UNKNOWN."""
    try:
        return DataPolicy(value)
    except ValueError:
        return DataPolicy.UNKNOWN


def resolve_span_id(span: Mapping[str, Any]) -> str | None:
    """Resolve a span's trace/span id from the open-convention id locations, or ``None``."""
    context = span.get("context")
    ctx = context if isinstance(context, Mapping) else {}
    for candidate in (
        ctx.get("trace_id"),
        span.get("trace_id"),
        ctx.get("span_id"),
        span.get("span_id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _maybe_json(value: Any, attributes: Mapping[str, Any], mime_key: str) -> Any:
    """Parse an OpenInference value that is JSON — a ``*.mime_type: application/json`` string, or a
    string that plainly parses as a JSON object/array — into the structured object it represents.

    OpenInference stores ``input.value``/``output.value`` as strings, marking structured payloads
    with ``*.mime_type``. Without this, a connector delivers ``output`` as a JSON *string* and a
    host evaluator expecting a mapping reads it as non-evaluable. A value that is already
    structured (a mapping/list, as the LangSmith connector delivers) or plain text is left as-is.
    """
    if not isinstance(value, str):
        return value
    mime = attributes.get(mime_key)
    looks_json = value.lstrip()[:1] in "{["
    if (isinstance(mime, str) and "json" in mime.lower()) or looks_json:
        try:
            return json.loads(value, parse_constant=_reject_constant)
        except (ValueError, TypeError):
            return value  # not actually JSON → keep the original string, never crash
    return value


def behavior_from_attributes(attributes: Mapping[str, Any]) -> dict[str, Any] | None:
    """Assemble vendor-neutral ``behavior`` from convention attributes, preserving behavior layers.

    Returns ``None`` only when the span carries no evaluable evidence at all — no application
    ``output`` **and** no preserved raw-model-output / parser-diagnostics layer. A span that a
    parser rejected (raw model output present, application output absent) is therefore evidence
    with its diagnostics, not a dropped record or a fabricated zero (B3). The raw model output and
    parser diagnostics are kept DISTINCT from ``output`` — they never replace it (B3 AC #3/#4), and
    an output-only span maps byte-identically to before (B3 AC #7 — no richer layer requested).
    """
    output = _first_present(attributes, _OUTPUT_KEYS)
    raw_output = _first_present(attributes, _RAW_OUTPUT_KEYS)
    parser_diags = _first_present(attributes, _PARSER_DIAG_KEYS)
    if output is None and raw_output is None and parser_diags is None:
        return None
    behavior: dict[str, Any] = {}
    if output is not None:
        behavior["output"] = _maybe_json(output, attributes, "output.mime_type")
    if raw_output is not None:
        # Kept RAW — it is the pre-parse model artifact; parsing it would erase the very distinction
        # from the application output (and a parser-rejected raw output is not valid JSON anyway).
        behavior["raw_output"] = raw_output
    if parser_diags is not None:
        behavior["parser_diagnostics"] = parser_diags
    for key, keys in (("input", _INPUT_KEYS), ("model", _MODEL_KEYS), ("tool_calls", _TOOL_KEYS)):
        value = _first_present(attributes, keys)
        if value is not None:
            behavior[key] = (
                _maybe_json(value, attributes, "input.mime_type") if key == "input" else value
            )
    return behavior


def map_span(
    span: Any,
    index: int,
    *,
    source: str,
    name: str,
    location_prefix: str,
    data_policy: str,
    build_metadata: Callable[[Mapping[str, Any]], dict[str, Any]],
    provenance: dict[str, Any],
    include_timing: bool = False,
) -> TraceUnit | Diagnostic:
    """Map one open-convention span to a ``TraceUnit`` (or a typed ``Diagnostic`` on a bad span)."""
    loc = f"{location_prefix}#span{index}"

    def diag(code: str, message: str) -> Diagnostic:
        return Diagnostic(code=code, severity=Severity.ERROR, message=message, location=loc)

    if not isinstance(span, Mapping):
        return diag("trace_invalid_record", f"span must be an object, got {type(span).__name__}")
    attributes = span.get("attributes", {})
    if not isinstance(attributes, Mapping):
        return diag("trace_invalid_record", "span 'attributes' must be an object")
    trace_id = resolve_span_id(span)
    if trace_id is None:
        return diag("trace_mapping_incomplete", "span has no resolvable trace/span id")
    behavior = behavior_from_attributes(attributes)
    if behavior is None:
        return diag("trace_mapping_incomplete", "span has no LLM output")
    if include_timing:
        timing = _extract_timing(span)
        if timing:
            behavior["timing"] = timing
    envelope_data = {
        "trace_id": trace_id,
        "source": source,
        "behavior": behavior,
        "data_policy": data_policy,
        "metadata": build_metadata(span),
        "provenance": provenance,
    }
    try:
        envelope = TraceEnvelope.from_dict(envelope_data)
    except ContractError as exc:  # defensive: behavior/trace_id already validated
        return diag("trace_invalid_record", str(exc))
    unit_id = str(span.get("span_id") or f"{name}#{index}")
    return TraceUnit(
        envelope=envelope, unit=EvalUnit(unit_id=unit_id, kind=UnitKind.CALL, trace_id=trace_id)
    )


def read_span_recording(
    path: Path,
    *,
    name: str,
    data_policy: str,
    unavailable_code: str,
    malformed_code: str,
    map_one: Callable[[Any, int], TraceUnit | Diagnostic],
) -> TraceRead:
    """Read a ``{"spans": [...]}`` recording and map each span via ``map_one`` (fail-closed).

    A missing file → ``unavailable_code``; non-JSON or a missing ``spans`` list → ``malformed_code``
    (typed diagnostics with no units — never a score). Per-span failures become diagnostics.
    """
    policy = policy_or_unknown(data_policy)

    def empty(code: str, message: str) -> TraceRead:
        diag = Diagnostic(code=code, severity=Severity.ERROR, message=message, location=str(path))
        return TraceRead(name=name, data_policy=policy, units=[], diagnostics=[diag])

    if not path.is_file():
        return empty(unavailable_code, f"recording not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (ValueError, OSError) as exc:
        return empty(malformed_code, f"recording not valid JSON: {exc}")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("spans"), list):
        return empty(malformed_code, "recording has no 'spans' list")

    units: list[TraceUnit] = []
    diagnostics: list[Diagnostic] = []
    for index, span in enumerate(payload["spans"]):
        mapped = map_one(span, index)
        (units if isinstance(mapped, TraceUnit) else diagnostics).append(mapped)  # type: ignore[arg-type]
    return TraceRead(name=name, data_policy=policy, units=units, diagnostics=diagnostics)
