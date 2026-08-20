# ADR 0035 — Phoenix trace connector

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** remaining product plan `jira_tickets_remaining_implementation_plan.xlsx` epic EG-R2 (EG-R2-1 … EG-R2-6); `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §M6-S7
- **Related:** [0033](0033-live-trace-connector-boundary.md) (cross-cutting connector boundary — governs everything below), [0018](0018-trace-backend-adapter.md), [0006](0006-open-convention-trace-mapping.md)

This ADR records only the **Phoenix-specific** decisions. The optionality, lazy
import, credential-handling, egress, normalization, deletion, and `live_lane`
rules are defined once in **ADR 0033** and inherited here.

## Decision

**Package and extra.** The connector uses the lightweight **`arize-phoenix-client`**
PyPI distribution (the HTTP client to a running Phoenix instance), declared under the
optional extra **`phoenix-trace`**. The full `arize-phoenix` server package is
*deliberately not* a dependency — EvalGlass reads spans from a Phoenix a host already
runs; it never embeds a Phoenix server. The exact pin is finalized in
`pyproject.toml`/`uv.lock` in EG-R0-2; the dependency-budget guard tracks the chosen
distribution name (`arize-phoenix-client`).

**Why optional.** Phoenix is one tracing backend among several. EvalGlass runs fully
without it, so the client SDK is opt-in and the required tier never imports it.

**Lazy import boundary.** The Phoenix client is imported **lazily**, inside the
connector's client factory / `read()` path only — never at module import time.
Importing `evalglass`, the runner, or `adapters/trace_phoenix.py` succeeds without the
`phoenix-trace` extra; a missing extra becomes a typed `MissingPrerequisite` skip when
the lane is enabled, reported only when the lane is resolved, never an `ImportError`.

**Credential model.** Credentials are host-owned **environment-variable references**,
read only when the lane is enabled: `PHOENIX_COLLECTOR_ENDPOINT` (base URL) and
`PHOENIX_CLIENT_HEADERS` / `PHOENIX_API_KEY` for authenticated instances. Literal
secrets are never accepted in config and never written to any artifact, report, or log.

**Keyless local collectors are supported; ambient pickup is blocked (decision).** Unlike
Langfuse (no anonymous read API — ADR 0034), Phoenix supports an **unauthenticated local
collector**, so the connector does **not** require an `api_key`: a lane with only an endpoint
is valid and pulls. To keep that mode honest without leaking undeclared credentials, the
connector passes `api_key` to the client **explicitly** — the lane-declared reference when
present, `None` when not — so the SDK cannot silently fall back to an ambient `PHOENIX_API_KEY`
the audited lane config never declared. Only lane-declared credential refs are forwarded. A
**declared** `api_key` whose env var fails to resolve is a misconfiguration → a clean
`MissingPrerequisite` skip, **never** a silent downgrade to a keyless/anonymous pull; `None` is
used only for the genuine no-credential-declared keyless-local case. (This is the deliberate
divergence from the Langfuse/LangSmith connectors, which DO require their keys before client
construction because their providers have no anonymous read mode.)

**Supported query scope.** A single read selects a Phoenix project/dataset plus an
optional time window and limit, paginated by the provider cursor. Out of scope:
writing/annotating Phoenix, evaluation runs inside Phoenix, and per-source-function
call-site correlation (`EG-M5C-7`, ADR-deferred).

**Normalization.** Phoenix span attributes (OpenInference-shaped) map to
`TraceEnvelope` + `EvalUnit`: trace id → `trace_id`, span id → `unit_id`,
input/output/messages/tools → `behavior`, model/usage attributes → metadata,
start/end → timing. Phoenix internal keys, cursors, and client/project objects are
dropped at the boundary and never reach the core.

**Failure handling.** Malformed payloads, auth failures, rate limits, timeouts,
empty pages, and pagination faults become a `phoenix_malformed_response` (or sibling)
`Diagnostic` and a `skipped`/`blocked` `LaneResult` — never a score or a core
`ScoreStatus.ERROR`.

**Deletion rule.** Deleting `adapters/trace_phoenix.py` leaves the required, hermetic
tier and the Langfuse/LangSmith connectors green (the lane resolves lazily; nothing on
a required path imports it).

**Test policy.** Required proof runs hermetically over local stub fixtures with no
socket (`m5c.trace.phoenix_normalization`). A real pull is a **`live_lane`** smoke
test, skipped unless `EVALGLASS_LIVE_LANES=1` **and** the Phoenix env vars are set; it
is manual, secret-gated, and not required for ordinary CI.

## Consequences

- A host running Phoenix can import its spans as an opt-in `TRACE_SOURCE` lane;
  EvalGlass without the extra is unaffected and stays offline and SDK-free.
- Choosing the client distribution over the full server keeps the optional footprint
  small and avoids pulling a server/UI into a host's dependency tree.
- Docs describe Phoenix support as an optional lane — never hosted telemetry, a
  required dependency, or certification.
