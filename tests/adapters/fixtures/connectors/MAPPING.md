# Connector mapping contract (EG-R0-7; ADR 0033)

Each live trace connector (Langfuse / Phoenix / LangSmith) normalizes its **provider-native**
payload into a vendor-neutral `TraceEnvelope` + `EvalUnit` at the adapter boundary. This file is the
shared contract: which native field becomes which normalized field. The fixture families in this
directory (`<provider>.json`) carry the native payloads and the declared `expected` normalized
output; the connector adapters (EG-R1…R3) must produce that `expected` over the matching `good` /
`vendor_wrapper` fixture, hermetically (no SDK, no socket).

The five normalized target fields, for every provider:

| Target | Meaning |
| --- | --- |
| `trace_id` | The id grouping a unit's behavior to its trace. |
| `unit_id` | The id of the evaluated behavior slice (the call/observation/run/span). |
| `behavior` | `{output, input?, model?}` — the vendor-neutral behavior the core evaluates. |
| `metadata` | Vendor-neutral extra facts (usage, run_type, …). Never a vendor object. |
| `timing` | `{start, end}` timestamps when present. |

Anything outside these fields — vendor wrapper objects, cursors, client/project/session objects
(each fixture lists them under `vendor_wrapper_keys`) — is **dropped at the boundary** and must
never appear in normalized output, the core, `RunRecord`, or `Scorecard`.

Each fixture's `expected` entry is contract-shaped — an `EvalUnit`
(`{unit_id, kind: "call", trace_id}`) plus the envelope `behavior` (`{output, input?, model?,
timing?}`, timing **inside** behavior) and `metadata`. The **connector-uniform** envelope fields are
not repeated per fixture entry; each connector sets them and asserts them in its own test:
`source` = the lane name (e.g. `langfuse-trace`), `data_policy` = the lane's configured policy, and
`provenance` = `{trace: <name>, provider: <provider>}`.

## Langfuse (`fetch_traces`; ADR 0034)

| Native field | → Target |
| --- | --- |
| `data[].id` | `trace_id` |
| `data[].observations[].id` | `unit_id` |
| `observations[].output` | `behavior.output` |
| `observations[].input` | `behavior.input` |
| `observations[].model` | `behavior.model` |
| `observations[].usage` | `metadata.usage` |
| `observations[].startTime` / `endTime` | `behavior.timing.start_time` / `.end_time` |
| `meta`, `_langfuse_client`, `_langfuse_internal` | **dropped** |

## Phoenix (`arize-phoenix-client`, OpenInference spans; ADR 0035)

| Native field | → Target |
| --- | --- |
| `spans[].context.trace_id` | `trace_id` |
| `spans[].context.span_id` | `unit_id` |
| `spans[].attributes["output.value"]` | `behavior.output` |
| `spans[].attributes["input.value"]` | `behavior.input` |
| `spans[].attributes["llm.model_name"]` | `behavior.model` |
| `spans[].start_time` / `end_time` | `behavior.timing.start_time` / `.end_time` |
| `project`, `_phoenix_cursor`, `_phoenix_internal` | **dropped** |

## LangSmith (`list_runs`; ADR 0036)

| Native field | → Target |
| --- | --- |
| `runs[].trace_id` | `trace_id` |
| `runs[].id` | `unit_id` |
| `runs[].outputs` | `behavior.output` |
| `runs[].inputs` | `behavior.input` |
| `runs[].extra.metadata.ls_model_name` | `behavior.model` |
| `runs[].run_type` | `metadata.run_type` |
| `runs[].start_time` / `end_time` | `behavior.timing.start_time` / `.end_time` |
| `cursors`, `_ls_client_session`, `_langsmith_run` | **dropped** |
