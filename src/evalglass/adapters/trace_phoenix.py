"""Opt-in Phoenix trace-import connector (EG-R2; ADR 0035).

An opt-in, deletable :class:`~evalglass.harness.ports.TraceSource` that imports recorded spans from
an Arize **Phoenix** instance via the lightweight ``arize-phoenix-client`` (top-level module
``phoenix``). The whole connector flow — runner-compatible constructor, egress gate, lazy fetch,
fail-closed paths, normalization to vendor-neutral ``TraceEnvelope``/``EvalUnit`` — is the shared
:class:`~evalglass.adapters._connector_boundary.BaseTraceConnector` (ADR 0033); this module supplies
only Phoenix specifics.

Phoenix spans are OpenInference-shaped, so the mapping is a near pass-through to the shared
``map_span`` (which diagnoses any malformed span itself); only the spans list crosses the boundary,
so Phoenix wrapper keys (``project``/``_phoenix_cursor``/internal objects) never reach the core.
The SDK is imported lazily inside the fetch path; the real pull is ``live_lane`` only (EG-R2-6).
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


class PhoenixTraceSource(BaseTraceConnector):
    """A :class:`~evalglass.harness.ports.TraceSource` backed by a Phoenix instance (opt-in)."""

    extra = "phoenix-trace"
    lane = "phoenix-trace"
    provider = "phoenix"
    import_name = "phoenix.client"
    endpoint_label = "Phoenix collector endpoint"

    def _default_fetch(self) -> Mapping[str, Any]:
        # Build the lazy arize-phoenix-client and read spans. Imported by name so the required tier
        # never imports the SDK (the hermetic tier exercises this path with an injected fake mod).
        client_mod = lazy_import(self.import_name, extra=self.extra)
        creds = resolve_credentials(self._opts.credentials)
        # Phoenix supports BOTH authenticated and credentialless local collectors (ADR 0035), so an
        # api_key is NOT required when none is declared. But a DECLARED api_key whose env var failed
        # to resolve is a misconfiguration → a clean MissingPrerequisite skip, never a silent
        # downgrade to a keyless/anonymous pull. Auth is passed ONLY from lane-declared refs, and
        # api_key is passed explicitly (``None`` for the genuine keyless-local mode) so the SDK
        # cannot fall back to an ambient PHOENIX_API_KEY the audited lane config never declared.
        if "api_key" in self._opts.credentials:
            require_prerequisite(creds.get("api_key"), what="Phoenix api_key credential")
        client_kwargs: dict[str, Any] = {"api_key": None, **creds}
        client = client_mod.Client(base_url=self._endpoint, **client_kwargs)
        # arize-phoenix-client v2 names the project ``project_identifier`` (not ``project_name``)
        # and defaults to the "default" project when the lane declares none. ``limit`` is passed
        # only when the lane declared one — the SDK rejects ``limit=None`` (it compares None<int),
        # so an unset limit falls through to the SDK's own default.
        span_kwargs: dict[str, Any] = {"project_identifier": self._opts.project or "default"}
        if self._opts.limit is not None:
            span_kwargs["limit"] = self._opts.limit
        spans = client.spans.get_spans(**span_kwargs)
        return {"spans": list(spans)}

    def _to_open_convention(
        self, payload: Mapping[str, Any]
    ) -> tuple[list[Any] | None, list[Diagnostic]]:
        """Build the open-convention spans the shared ``map_span`` consumes, or ``(None, [])`` when
        the response shape is malformed (→ one malformed diagnostic).

        Phoenix spans are OpenInference-shaped, but the span id lives in ``context.span_id`` while
        ``map_span`` resolves a unit id from a top-level ``span_id``; so each span is rebuilt with
        only the known fields — vendor wrapper keys are never copied, and a non-object span is
        passed through for ``map_span`` to diagnose (no silent drop)."""
        if not isinstance(payload, Mapping) or not isinstance(payload.get("spans"), list):
            return None, []
        spans: list[Any] = []
        for span in payload["spans"]:
            if not isinstance(span, Mapping):
                spans.append(span)  # not an object → map_span emits a diagnostic
                continue
            raw_ctx = span.get("context")
            context: Mapping[str, Any] = raw_ctx if isinstance(raw_ctx, Mapping) else {}
            span_id = context.get("span_id")
            clean: dict[str, Any] = {
                "context": {"trace_id": context.get("trace_id"), "span_id": span_id},
                "span_id": span_id,
                "attributes": span.get("attributes", {}),
            }
            # Carry the span name as ``trace_name`` so downstream evaluators can dispatch by
            # workflow — the host names the workflow span (as the Langfuse trace name does).
            # Without this the Phoenix envelope carries no metadata and every workflow-scoped
            # metric reads as non_applicable.
            name = span.get("name")
            if isinstance(name, str) and name:
                clean["_eg_metadata"] = {"trace_name": name}
            for key in ("start_time", "end_time"):
                if isinstance(span.get(key), str):
                    clean[key] = span[key]
            spans.append(clean)
        return spans, []
