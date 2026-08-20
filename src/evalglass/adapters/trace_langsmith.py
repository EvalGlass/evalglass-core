"""Opt-in LangSmith trace-import connector (EG-R3; ADR 0036).

An opt-in, deletable :class:`~evalglass.harness.ports.TraceSource` that imports recorded runs from a
LangSmith instance via the official ``langsmith`` client. The whole connector flow —
runner-compatible constructor, egress gate, lazy fetch, fail-closed paths, normalization to
vendor-neutral ``TraceEnvelope``/``EvalUnit`` — is the shared
:class:`~evalglass.adapters._connector_boundary.BaseTraceConnector` (ADR 0033); this module supplies
only LangSmith specifics: the SDK pull and the native run → open-convention mapping.

A connector imports **evidence, never authority**: ``read()`` yields a ``TraceRead`` only. LangSmith
internal run objects, cursors, and client/session objects (``cursors``/``_ls_client_session``/
``_langsmith_run``) are never read, so they cannot leak; a malformed entry is a typed ``Diagnostic``
(never a silent drop). Only ``langsmith`` is imported — never ``langchain`` (ADR 0036). The SDK is
imported lazily inside the fetch path (injected as ``fetch`` for the hermetic tier); the real pull
is ``live_lane`` only (EG-R3-6).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evalglass.adapters._connector_boundary import (
    BaseTraceConnector,
    lazy_import,
    require_prerequisite,
    resolve_credentials,
)
from evalglass.core import Diagnostic


def _run_field(run: Any, key: str) -> Any:
    """Read one field from a LangSmith run, whether it arrives as a Mapping or an SDK object."""
    if isinstance(run, Mapping):
        return run.get(key)
    return getattr(run, key, None)


def _model_from_extra(extra: Any) -> str | None:
    """Pull the model name out of a run's ``extra.metadata`` (LangSmith stores it there)."""
    if not isinstance(extra, Mapping):
        return None
    metadata = extra.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    model = metadata.get("ls_model_name")
    return model if isinstance(model, str) else None


def _coerce_span_id(value: Any) -> str | None:
    """Coerce a LangSmith id (the SDK returns ``UUID``) to a string; ``None`` stays ``None``."""
    if value is not None and not isinstance(value, str):
        return str(value)
    return value


def _span_attributes(run: Mapping[str, Any]) -> dict[str, Any]:
    """The open-convention ``attributes`` for a run: whole inputs/outputs payloads + model."""
    attributes: dict[str, Any] = {}
    if run.get("outputs") is not None:
        attributes["output.value"] = run["outputs"]
    if run.get("inputs") is not None:
        attributes["input.value"] = run["inputs"]
    model = _model_from_extra(run.get("extra"))
    if model is not None:
        attributes["llm.model_name"] = model
    return attributes


def _eg_metadata(run: Mapping[str, Any]) -> dict[str, Any]:
    """``_eg_metadata`` carried alongside a span: the run name (trace_name) and run_type."""
    eg_meta: dict[str, Any] = {}
    run_name = run.get("name")
    if isinstance(run_name, str) and run_name:
        eg_meta["trace_name"] = run_name
    if run.get("run_type") is not None:
        eg_meta["run_type"] = run["run_type"]
    return eg_meta


class LangSmithTraceSource(BaseTraceConnector):
    """A :class:`~evalglass.harness.ports.TraceSource` backed by a LangSmith instance (opt-in)."""

    extra = "langsmith-trace"
    lane = "langsmith-trace"
    provider = "langsmith"
    import_name = "langsmith"
    endpoint_label = "LangSmith API endpoint"

    def _default_fetch(self) -> Mapping[str, Any]:
        # Build the lazy LangSmith client and list runs. Imported by name so the required tier never
        # imports the SDK (and never LangChain); the hermetic tier always injects ``fetch`` (this
        # default path is exercised hermetically only with an injected fake ``langsmith`` module).
        langsmith = lazy_import(self.import_name, extra=self.extra)
        creds = resolve_credentials(self._opts.credentials)
        # Enforce the declared API-credentials prerequisite BEFORE constructing the client: a
        # missing key is a clean MissingPrerequisite skip, never a keyless provider call. The SDK
        # otherwise silently reads ``LANGSMITH_API_KEY`` from the ambient environment — egress
        # with a credential the audited lane config never declared. Every resolved credential is
        # then forwarded explicitly (``**creds``) so all declared credentials — including
        # ``workspace_id`` for org-scoped keys — stay in the lane config and ambient pickup is gone.
        require_prerequisite(creds.get("api_key"), what="LangSmith API credentials")
        # Forward the host-declared evidence scope so the pull is not broader than configured: an
        # ignored time window / query would import runs the host never asked for. Only the genuinely
        # supported ``list_runs`` filters are passed (``start_time`` lower bound, ``filter`` query
        # string); ``end_time`` is folded into ``filter`` once finalized against the installed SDK.
        list_kwargs: dict[str, Any] = {
            "project_name": self._opts.project,
            "limit": self._opts.limit,
        }
        if self._opts.start_time is not None:
            list_kwargs["start_time"] = self._opts.start_time
        if self._opts.query is not None:
            list_kwargs["filter"] = self._opts.query
        client = langsmith.Client(api_url=self._endpoint, **creds)
        runs = client.list_runs(**list_kwargs)
        return {"runs": [self._serialize_run(run) for run in runs]}

    @staticmethod
    def _serialize_run(run: Any) -> dict[str, Any]:  # pragma: no cover - live_lane only
        # Reduce an SDK Run to the known open-convention input fields only — vendor internals are
        # never carried. Datetimes become ISO strings (the shared timing extractor expects strings).
        def iso(value: Any) -> Any:
            return value.isoformat() if hasattr(value, "isoformat") else value

        return {
            "id": _run_field(run, "id"),
            "trace_id": _run_field(run, "trace_id"),
            "name": _run_field(run, "name"),
            "run_type": _run_field(run, "run_type"),
            "inputs": _run_field(run, "inputs"),
            "outputs": _run_field(run, "outputs"),
            "start_time": iso(_run_field(run, "start_time")),
            "end_time": iso(_run_field(run, "end_time")),
            "extra": _run_field(run, "extra"),
        }

    def _to_open_convention(
        self, payload: Mapping[str, Any]
    ) -> tuple[list[Any] | None, list[Diagnostic]]:
        """Map LangSmith runs to open-convention spans (the shared mapping's input).

        Only the contract fields cross the boundary; LangSmith wrapper keys (``cursors``/
        ``_ls_client_session``/``_langsmith_run``) are never read. A non-list ``runs`` returns
        ``(None, [])`` so the shared normalizer emits one malformed diagnostic. A malformed *entry*
        (a non-object run) becomes a diagnostic — never a silent drop that would read as an empty,
        clean import. ``run_type`` is stashed under ``_eg_metadata`` for the shared build_metadata;
        the whole ``inputs``/``outputs`` payloads map to ``input.value``/``output.value``.
        """
        if not isinstance(payload, Mapping) or not isinstance(payload.get("runs"), list):
            return None, []
        spans: list[Any] = []
        diagnostics: list[Diagnostic] = []
        for index, run in enumerate(payload["runs"]):
            span, diagnostic = self._span_from_run(run, index)
            if diagnostic is not None:
                diagnostics.append(diagnostic)
            if span is not None:
                spans.append(span)
        return spans, diagnostics

    def _span_from_run(
        self, run: Any, index: int
    ) -> tuple[dict[str, Any] | None, Diagnostic | None]:
        """One LangSmith run → an open-convention span, or a diagnostic for a malformed entry.

        A non-object run becomes a diagnostic, never a silent drop that would read as a clean,
        empty import. Ids are coerced from the SDK's ``UUID`` objects to strings (``map_span``
        only resolves string ids); ``None`` stays ``None`` → fail-closed mapping diagnostic. The
        run name travels as ``trace_name`` (workflow dispatch) so workflow-scoped metrics apply.
        """
        if not isinstance(run, Mapping):
            return None, self._malformed(f"run entry {index} is not an object")
        run_id = _coerce_span_id(run.get("id"))
        trace_id = _coerce_span_id(run.get("trace_id"))
        span: dict[str, Any] = {
            "context": {"trace_id": trace_id, "span_id": run_id},
            "span_id": run_id,
            "attributes": _span_attributes(run),
        }
        if isinstance(run.get("start_time"), str):
            span["start_time"] = run["start_time"]
        if isinstance(run.get("end_time"), str):
            span["end_time"] = run["end_time"]
        eg_meta = _eg_metadata(run)
        if eg_meta:
            span["_eg_metadata"] = eg_meta
        return span, None
