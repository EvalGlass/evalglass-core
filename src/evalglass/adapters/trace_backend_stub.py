"""Optional trace-backend **stub** lane (EG-M5-3; ADR 0018).

An opt-in, deletable :class:`~evalglass.harness.ports.TraceSource` that proves the *contract* for
attaching a real tracing backend (Phoenix, Langfuse, …) **without** any vendor SDK or network: the
"backend" is a local JSON file standing in for a backend query response. The adapter normalizes the
backend's spans into vendor-neutral :class:`~evalglass.core.TraceEnvelope` records at the boundary,
so **no vendor object ever reaches the core, evaluators, RunRecord, or Scorecard** — only the
``spans`` are mapped; any vendor wrapper/metadata (e.g. ``_backend_internal``) is dropped.

It is a lane (EG-M5-1; ADR 0017): no required path imports it, deleting it leaves the local JSONL
trace route intact, and an absent backend is a skip/diagnostic — never a crash or a low score.
A real backend adapter replaces the file read with an SDK/HTTP query behind this same shape; the
mapping and the boundary stay identical (shared ``_span_mapping``). Standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evalglass.adapters._span_mapping import map_span, read_span_recording
from evalglass.core import Diagnostic
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceUnit


class StubBackendTraceSource:
    """A :class:`~evalglass.harness.ports.TraceSource` backed by a stubbed backend response file."""

    def __init__(
        self,
        *,
        backend_path: str | None,
        root: Path,
        query: str = "",
        data_policy: str = "unknown",
        name: str = "trace-backend",
    ) -> None:
        if not backend_path:
            # Opt-in: with no backend configured the lane is unavailable and simply does not run.
            raise MissingPrerequisite(
                "no trace backend configured; the trace-backend lane is unavailable"
            )
        self._path = root / backend_path
        self._query = query
        self._data_policy = data_policy
        self._name = name

    def read(self) -> TraceRead:
        return read_span_recording(
            self._path,
            name=self._name,
            data_policy=self._data_policy,
            unavailable_code="backend_unavailable",
            malformed_code="backend_malformed_response",
            map_one=self._map_one,
        )

    def _map_one(self, span: Any, index: int) -> TraceUnit | Diagnostic:
        # include_timing: a backend records span timing; the vendor wrapper is never carried.
        return map_span(
            span,
            index,
            source="trace-backend-stub",
            name=self._name,
            location_prefix=str(self._path),
            data_policy=self._data_policy,
            build_metadata=self._metadata,
            provenance={"trace": self._name, "backend": "stub", "query": self._query},
            include_timing=True,
        )

    def _metadata(self, span: Mapping[str, Any]) -> dict[str, Any]:
        del span
        return {"backend": "stub", "query": self._query}
