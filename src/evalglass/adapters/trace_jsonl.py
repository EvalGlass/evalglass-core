"""Local JSONL ``TraceSource`` adapter (EG-M1-3a).

Reads a host-owned local trace ``*.jsonl`` and normalizes each record into a vendor-neutral
:class:`~evalglass.core.TraceEnvelope` plus a call-level :class:`~evalglass.core.EvalUnit`.
The local record is itself neutral (``trace_id`` + ``behavior`` object, optional
``data_policy``/``metadata``/``unit_id``); normalization runs it through the core's
fail-closed ``TraceEnvelope.from_dict`` so a malformed record becomes a
:class:`~evalglass.core.Diagnostic`, never a low score. Provider-shaped traces
(OpenTelemetry/OpenInference) are a separate adapter in slice 3b — the core only ever sees
``TraceEnvelope``. A missing file is a setup error.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evalglass.adapters._jsonl import read_trace_jsonl
from evalglass.core import ContractError, Diagnostic, EvalUnit, Severity, TraceEnvelope, UnitKind
from evalglass.harness.config import TraceConfig
from evalglass.harness.ports import TraceRead, TraceUnit


class LocalJsonlTraceSource:
    """A :class:`~evalglass.harness.ports.TraceSource` backed by a local trace JSONL file."""

    def __init__(self, config: TraceConfig, root: Path) -> None:
        self._config = config
        self._root = root

    def read(self) -> TraceRead:
        return read_trace_jsonl(self._config, self._root, self._unit, adapter="local_jsonl")

    def _unit(self, record: Any, lineno: int, loc: str) -> TraceUnit | Diagnostic:
        def bad(message: str) -> Diagnostic:
            return Diagnostic(
                code="trace_invalid_record", severity=Severity.ERROR, message=message, location=loc
            )

        if not isinstance(record, Mapping):
            return bad(f"trace record must be a JSON object, got {type(record).__name__}")
        raw_provenance = record.get("provenance", {})
        if not isinstance(raw_provenance, Mapping):
            # Fail closed: we merge into provenance ourselves, so the core parser never sees
            # the raw value — validate it here rather than silently dropping a malformed one.
            return bad("trace record 'provenance' must be an object")
        provenance = dict(raw_provenance)
        provenance.update({"trace": self._config.name, "line": lineno})
        # Normalize through the core's fail-closed parser; the local record is already
        # vendor-neutral, so this is the trace_id/behavior/data_policy validation boundary.
        envelope_data = {
            "trace_id": record.get("trace_id"),
            "source": record.get("source", "local_jsonl"),
            "behavior": record.get("behavior"),
            "data_policy": record.get("data_policy", self._config.data_policy.value),
            "metadata": record.get("metadata", {}),
            "provenance": provenance,
        }
        try:
            envelope = TraceEnvelope.from_dict(envelope_data)
        except ContractError as exc:
            return bad(str(exc))
        raw_unit_id = record.get("unit_id")
        if raw_unit_id is not None and (
            isinstance(raw_unit_id, bool) or not isinstance(raw_unit_id, str | int)
        ):
            return bad("trace record 'unit_id' must be a string or integer")
        unit_id = (
            str(raw_unit_id).strip() if raw_unit_id is not None else f"{self._config.name}#{lineno}"
        )
        if not unit_id:
            return bad("trace record 'unit_id' must not be empty")
        return TraceUnit(
            envelope=envelope,
            unit=EvalUnit(unit_id=unit_id, kind=UnitKind.CALL, trace_id=envelope.trace_id),
        )
