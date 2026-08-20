"""Optional async-observation lane (EG-M5-5 S1c; ADR 0020/0017).

An opt-in, deletable :class:`~evalglass.harness.ports.TraceSource` that **observes recorded async
behavior** — interleaved/concurrent spans captured from a prior run — and normalizes them into
vendor-neutral :class:`~evalglass.core.TraceEnvelope`s. It **only reads a recorded file**; it never
orchestrates, runs, or calls the host (build contract §6/§9; EG-M5-5 acceptance: "async support
observes recorded behavior and does not orchestrate host workflows"). Async metadata
(``parent_span_id``, ``concurrent``) is carried through as envelope metadata; the core sees only the
normalized envelope. Standard library only — no subprocess, no network, no host runner.

The recorded shape is ``{"spans": [ <open-convention span>, ... ]}``; spans map via the shared
``_span_mapping`` helpers. Absent source → :class:`MissingPrerequisite` (skip).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evalglass.adapters._span_mapping import map_span, read_span_recording
from evalglass.core import Diagnostic
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceUnit

_ASYNC_META_KEYS = ("parent_span_id", "concurrent", "start_time", "end_time")


class AsyncObservationTraceSource:
    """Observe recorded async spans from a file; normalize to TraceEnvelope (no orchestration)."""

    def __init__(
        self,
        *,
        recording_path: str | None,
        root: Path,
        data_policy: str = "unknown",
        name: str = "async-observation",
    ) -> None:
        if not recording_path:
            raise MissingPrerequisite(
                "no async recording configured; the async-observation lane is unavailable"
            )
        self._path = root / recording_path
        self._data_policy = data_policy
        self._name = name

    def read(self) -> TraceRead:
        return read_span_recording(
            self._path,
            name=self._name,
            data_policy=self._data_policy,
            unavailable_code="async_recording_unavailable",
            malformed_code="async_recording_malformed",
            map_one=self._map_one,
        )

    def _map_one(self, span: Any, index: int) -> TraceUnit | Diagnostic:
        return map_span(
            span,
            index,
            source="async-observation",
            name=self._name,
            location_prefix=str(self._path),
            data_policy=self._data_policy,
            build_metadata=self._metadata,
            provenance={"trace": self._name, "observation": "async"},
        )

    @staticmethod
    def _metadata(span: Mapping[str, Any]) -> dict[str, Any]:
        # Carry async observation metadata (recorded fact, never an orchestration handle).
        metadata: dict[str, Any] = {"observation": "async", "convention": "async"}
        async_meta = {k: span[k] for k in _ASYNC_META_KEYS if k in span}
        if async_meta:
            metadata["async"] = async_meta
        return metadata
