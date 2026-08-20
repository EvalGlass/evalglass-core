# ADR 0006 — Open-convention (OpenTelemetry / OpenInference) trace mapping subset

- **Status:** accepted
- **Date:** 2026-05-29
- **Extended by:** M5a Slice 2 (EG-M5-2) — adds two **optional** mappings to the
  pinned subset: tool calls (`llm.tools` / `tool_calls` / `message.tool_calls` /
  `gen_ai.tool.calls`) and span timing (`start_time` / `end_time` / `duration_ms`).
  Additive only; a span without them still maps, and the core still branches on no
  convention type (proven by the EGTS-M5-2 conformance lane).

## Context

EG-M1-3 requires that OpenTelemetry / OpenInference-shaped traces can be mapped into
`TraceEnvelope` "without provider SDKs" (architecture.md §4; build contract §6). The
design principles fix route convergence and trace capability but deliberately leave
*which* fields are adopted to the architecture/implementation phase (P10; principles §7).
This ADR pins the subset M1 maps, so the boundary is explicit and testable.

The required tier must stay hermetic: no tracing-backend SDK may be imported (EGTS-M1-4
negative control). The mapper therefore operates on **static JSON dicts** (a span per JSONL
line), not live SDK objects.

## Decision

`OpenConventionTraceSource` maps one span record to a `TraceEnvelope` using this subset:

| Envelope field | Source attributes (first present wins) |
|---|---|
| `trace_id` | `context.trace_id` → `trace_id` → `context.span_id` → `span_id` |
| `behavior.input` | `llm.input_messages` (OpenInference) → `input.value` → `gen_ai.prompt` (OTel) |
| `behavior.output` | `llm.output_messages` → `output.value` → `gen_ai.completion` |
| `behavior.model` | `llm.model_name` → `gen_ai.request.model` |

- `source` is the configured convention (`openinference` / `opentelemetry`); `data_policy`
  comes from the trace config; `metadata` carries the span name + convention; provenance
  records trace/line/convention.
- **Required:** a resolvable id and an extractable `output`. Missing either yields a visible
  `trace_mapping_incomplete` diagnostic — never a low score. A non-object record/`attributes`
  yields `trace_invalid_record`; a non-standard JSON token yields `trace_invalid_json`.
- The normalized envelope is built through the core's fail-closed `TraceEnvelope.from_dict`,
  so the core never sees a provider-shaped value.

## Consequences

- The mapped surface is small and explicit; broader coverage (events-based OTel GenAI
  payloads, tool-call spans, multi-span trajectories) is a later, additive lane (M5),
  not a day-one obligation.
- No `opentelemetry` / `openinference` import on any required path; the mapper is pure and
  hermetic. A backend/SDK-fed adapter is a separate optional lane (EGTS-M5-3).

## Alternatives considered

- **Depend on the OpenTelemetry SDK / OpenInference instrumentors.** Rejected for the
  required tier — it would make a tracing backend a hard dependency of the local product
  and break hermeticity. SDK-fed ingestion belongs in an optional M5 lane.
- **Accept any attribute shape and best-effort guess I/O.** Rejected — silent best-effort
  mapping manufactures evaluable examples from ambiguous spans. Failing closed with a
  mapping diagnostic is the honest behavior.
