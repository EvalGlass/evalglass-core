"""Opt-in Langfuse trace-import connector (EG-R1; ADR 0034).

An opt-in, deletable :class:`~evalglass.harness.ports.TraceSource` that imports recorded behavior
from a Langfuse instance. The whole connector flow — runner-compatible constructor, egress gate,
lazy fetch, fail-closed paths, normalization to vendor-neutral ``TraceEnvelope``/``EvalUnit`` — is
the shared :class:`~evalglass.adapters._connector_boundary.BaseTraceConnector` (ADR 0033); this
module supplies only Langfuse specifics: the SDK pull and the native trace/observation →
open-convention mapping.

A connector imports **evidence, never authority**: ``read()`` yields a ``TraceRead`` only. Langfuse
wrapper keys (``meta``/``_langfuse_client``/``_langfuse_internal``) are never read, so they cannot
leak; a malformed entry is a typed ``Diagnostic`` (never a silent drop). The SDK is imported lazily
inside the fetch path (injected as ``fetch`` for the hermetic tier); the real pull is ``live_lane``
only (EG-R1-6).
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
from evalglass.harness.coverage import TRACE_LEVEL_FALLBACK_SPAN_KEY
from evalglass.harness.lanes import MissingPrerequisite


class LangfuseTraceSource(BaseTraceConnector):
    """A :class:`~evalglass.harness.ports.TraceSource` backed by a Langfuse instance (opt-in)."""

    extra = "langfuse-trace"
    lane = "langfuse-trace"
    provider = "langfuse"
    import_name = "langfuse"
    endpoint_label = "Langfuse host/endpoint"

    #: A generous read timeout (seconds): a self-hosted Langfuse's list endpoint can be slow, and
    #: the SDK's default would time out mid-pull (EG-R1 live-hardening).
    _FETCH_TIMEOUT_S = 30.0

    #: Upper bound on child observations hydrated per read (B3) — a fixed ceiling so a large export
    #: can never fan out into an unbounded number of provider calls. A shortfall stays partial.
    _MAX_HYDRATED_OBSERVATIONS = 500

    def _enrich_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Hydrate bare-ID observation lists into full observation objects (bounded) (B3).

        Langfuse's public trace-list endpoint returns each trace's ``observations`` as bare IDs; the
        pre-B3 behavior flattened such a trace to a single trace-level fallback span. Here, up to
        :attr:`_MAX_HYDRATED_OBSERVATIONS` bare IDs are hydrated into observation objects (via
        :meth:`_hydrate_observations`, the live/injected seam) and replace the IDs, so the trace
        maps to observation-level spans instead. A trace whose IDs are only partially hydrated keeps
        hydrated observations (the source reads partial); a trace with no hydration falls back as
        before. Runs after the egress gate, so every hydration call is already policy-checked.
        """
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            return payload
        budget = self._MAX_HYDRATED_OBSERVATIONS
        traces: list[Any] = []
        changed = False
        for trace in payload["data"]:
            bare_ids = _bare_observation_ids(trace)[:budget] if budget > 0 else []
            hydrated = self._hydrate_observations(trace.get("id"), bare_ids) if bare_ids else []
            if hydrated:
                budget -= len(bare_ids)
                traces.append({**trace, "observations": hydrated})
                changed = True
            else:
                traces.append(trace)
        return {**payload, "data": traces} if changed else payload

    def _hydrate_observations(
        self, _trace_id: Any, observation_ids: list[str]
    ) -> list[Mapping[str, Any]]:
        """Live seam: fetch each observation object by id (one client), skipping any that fail.

        Best-effort: if the SDK/credentials are unavailable, or a given observation cannot be
        fetched, that hydration is skipped and the caller falls back (the read stays partial) rather
        than failing the whole read. The hermetic tier monkeypatches this method, so importing the
        connector never touches the SDK.
        """
        try:
            langfuse = lazy_import(self.import_name, extra=self.extra)
            creds = resolve_credentials(self._opts.credentials)
            require_prerequisite(creds.get("public_key"), what="Langfuse public_key credential")
            require_prerequisite(creds.get("secret_key"), what="Langfuse secret_key credential")
            client = langfuse.Langfuse(host=self._endpoint, timeout=self._FETCH_TIMEOUT_S, **creds)
        except MissingPrerequisite:
            return []  # SDK/creds absent → cannot hydrate; caller falls back to trace-level
        out: list[Mapping[str, Any]] = []
        for obs_id in observation_ids:
            try:
                obj = _one_plain(client.api.observations.get(obs_id))
            except Exception:  # noqa: S112  # nosec B112 - per-observation fault is a partial
                continue
            if isinstance(obj, Mapping):
                out.append(obj)
        return out

    def _default_fetch(self) -> Mapping[str, Any]:
        # Build the lazy Langfuse client and list traces. Imported by name so the required tier
        # never imports the SDK (the hermetic tier exercises this path with an injected fake mod).
        langfuse = lazy_import(self.import_name, extra=self.extra)
        creds = resolve_credentials(self._opts.credentials)
        # Enforce Langfuse's declared credentials BEFORE constructing the client: Langfuse has no
        # anonymous read API (ADR 0034), and the SDK otherwise reads ambient LANGFUSE_PUBLIC_KEY /
        # LANGFUSE_SECRET_KEY from the environment — egress under a credential the audited lane
        # config never declared. A missing key is a clean MissingPrerequisite skip; every resolved
        # credential is then forwarded explicitly (``**creds``) so ambient pickup is blocked.
        require_prerequisite(creds.get("public_key"), what="Langfuse public_key credential")
        require_prerequisite(creds.get("secret_key"), what="Langfuse secret_key credential")
        client = langfuse.Langfuse(host=self._endpoint, timeout=self._FETCH_TIMEOUT_S, **creds)
        result = client.api.trace.list(limit=self._opts.limit)
        # The SDK returns a pydantic model whose ``.data`` is a list of pydantic trace models;
        # serialize to plain JSON dicts so only contract fields (never SDK objects) cross into the
        # mapping. A dict-shaped result (the hermetic injected fetch) passes through unchanged.
        return _as_plain(result)

    def _to_open_convention(
        self, payload: Mapping[str, Any]
    ) -> tuple[list[Any] | None, list[Diagnostic]]:
        """Map Langfuse traces/observations to open-convention spans (the shared mapping's input).

        Only the contract fields cross the boundary; Langfuse wrapper keys are never read. A
        non-list ``data`` returns ``(None, [])`` so the shared normalizer emits one malformed
        diagnostic. Two real Langfuse shapes are handled: a trace whose ``observations`` are full
        objects (per-observation call-level spans) and a trace whose ``observations`` are bare IDs
        (the public list endpoint) — for the latter the **trace-level** ``output``/``input`` is the
        workflow result and becomes one span. Every span carries the trace ``name`` (the workflow)
        and ``sessionId`` under ``_eg_metadata`` so downstream evaluation can dispatch by workflow.
        A malformed entry (non-object trace, or a trace with neither observations nor an output)
        becomes a diagnostic — never a silent drop that reads as an empty, clean import.
        """
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            return None, []
        spans: list[Any] = []
        diagnostics: list[Diagnostic] = []
        for index, trace in enumerate(payload["data"]):
            if not isinstance(trace, Mapping):
                diagnostics.append(self._malformed(f"trace entry {index} is not an object"))
                continue
            trace_id = trace.get("id")
            trace_meta: dict[str, Any] = {}
            if isinstance(trace.get("name"), str):
                trace_meta["trace_name"] = trace["name"]
            if isinstance(trace.get("sessionId"), str):
                trace_meta["session_id"] = trace["sessionId"]
            observations = trace.get("observations")
            full_obs = (
                [o for o in observations if isinstance(o, Mapping)]
                if isinstance(observations, list)
                else []
            )
            if full_obs:
                for obs in full_obs:
                    spans.append(self._observation_span(trace_id, obs, trace_meta))
            elif trace.get("output") is not None:
                spans.append(self._trace_span(trace_id, trace, trace_meta))
            else:
                diagnostics.append(
                    self._malformed(
                        f"trace {trace_id!r} has neither full observations nor a trace output"
                    )
                )
        return spans, diagnostics

    @staticmethod
    def _observation_span(
        trace_id: Any, obs: Mapping[str, Any], trace_meta: Mapping[str, Any]
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        if obs.get("output") is not None:
            attributes["output.value"] = obs["output"]
        if obs.get("input") is not None:
            attributes["input.value"] = obs["input"]
        if obs.get("model") is not None:
            attributes["llm.model_name"] = obs["model"]
        span: dict[str, Any] = {
            "context": {"trace_id": trace_id, "span_id": obs.get("id")},
            "span_id": obs.get("id"),
            "attributes": attributes,
        }
        if isinstance(obs.get("startTime"), str):
            span["start_time"] = obs["startTime"]
        if isinstance(obs.get("endTime"), str):
            span["end_time"] = obs["endTime"]
        eg_meta = dict(trace_meta)
        if obs.get("usage") is not None:
            eg_meta["usage"] = obs["usage"]
        if eg_meta:
            span["_eg_metadata"] = eg_meta
        return span

    @staticmethod
    def _trace_span(
        trace_id: Any, trace: Mapping[str, Any], trace_meta: Mapping[str, Any]
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {"output.value": trace["output"]}
        if trace.get("input") is not None:
            attributes["input.value"] = trace["input"]
        span: dict[str, Any] = {
            "context": {"trace_id": trace_id, "span_id": trace_id},
            "span_id": trace_id,
            "attributes": attributes,
        }
        if isinstance(trace.get("timestamp"), str):
            span["start_time"] = trace["timestamp"]
        if trace_meta:
            span["_eg_metadata"] = dict(trace_meta)
        # Mark this span as a trace-level fallback (no hydrated observations) so the coverage
        # manifest counts it distinctly. A top-level key map_span ignores → never evaluator-visible.
        span[TRACE_LEVEL_FALLBACK_SPAN_KEY] = True
        return span


def _as_plain(result: Any) -> Mapping[str, Any]:
    """Serialize a Langfuse SDK response (or dict) to a plain ``{"data": [dict, ...]}`` mapping.

    The SDK returns a pydantic model with a ``.data`` list of pydantic trace models; ``model_dump``
    (JSON mode, so datetimes become strings) yields contract-only dicts. A dict-shaped result (the
    hermetic injected fetch) is returned unchanged so the fixture tier is untouched.
    """
    if isinstance(result, Mapping):
        return result
    data = getattr(result, "data", result)
    items = [_one_plain(t) for t in data] if isinstance(data, list) else data
    return {"data": items}


def _one_plain(item: Any) -> Any:
    """Serialize one Langfuse SDK pydantic model to a plain JSON dict (a dict passes through)."""
    dump = getattr(item, "model_dump", None)
    return dump(mode="json") if callable(dump) else item


def _bare_observation_ids(trace: Any) -> list[str]:
    """A trace's ``observations`` when they are bare IDs (not full objects); else empty (B3)."""
    obs = trace.get("observations") if isinstance(trace, Mapping) else None
    if not isinstance(obs, list) or any(isinstance(o, Mapping) for o in obs):
        return []
    return [o for o in obs if isinstance(o, str) and o.strip()]
