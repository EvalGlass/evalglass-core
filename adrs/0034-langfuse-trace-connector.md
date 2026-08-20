# ADR 0034 — Langfuse trace connector

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** remaining product plan `jira_tickets_remaining_implementation_plan.xlsx` epic EG-R1 (EG-R1-1 … EG-R1-6); `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §M6-S6
- **Related:** [0033](0033-live-trace-connector-boundary.md) (cross-cutting connector boundary — governs everything below), [0018](0018-trace-backend-adapter.md), [0006](0006-open-convention-trace-mapping.md)

This ADR records only the **Langfuse-specific** decisions. The optionality, lazy
import, credential-handling, egress, normalization, deletion, and `live_lane`
rules are defined once in **ADR 0033** and inherited here.

## Decision

**Package and extra.** The connector uses the official **`langfuse`** PyPI
distribution, declared under the optional extra **`langfuse-trace`**. It is never a
runtime dependency. The exact pin (a floor on the current major release line with a
next-major ceiling, e.g. `>=2,<4`) is finalized in `pyproject.toml`/`uv.lock` in
EG-R0-2; this ADR fixes the *package selection* and *that it is optional*.

**Why optional.** Langfuse is one of several tracing backends a host *might* run.
EvalGlass must work fully without it, so the SDK is opt-in and the required tier
never imports it.

**Lazy import boundary.** `langfuse` is imported **lazily**, inside the connector's
client factory / `read()` path only — never at module import time. Importing
`evalglass`, the runner, or `adapters/trace_langfuse.py` itself succeeds without the
`langfuse-trace` extra installed; a missing extra becomes a typed
`MissingPrerequisite` skip when the lane is enabled, not an `ImportError`.

**Credential model.** Credentials are host-owned **environment-variable references**,
read only when the lane is enabled: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and
`LANGFUSE_HOST` (endpoint). Literal secrets are never accepted in config and never
written to `RunRecord.lane_results`, `Scorecard`, reports, logs, or evidence packs.
Langfuse has **no anonymous read API**, so the connector enforces both `public_key` and
`secret_key` (resolved from their env-var references) **before constructing the client** — a
missing key is a clean `MissingPrerequisite` skip, never a keyless call — and forwards the
resolved credentials explicitly so the SDK cannot fall back to ambient `LANGFUSE_*` env the
audited lane config never declared.

**Supported query scope.** A single read selects a project plus an optional time
window and result limit (e.g. `client.api.trace.list(...)` / fetch-traces),
paginated by the provider cursor. Out of scope: writing/annotating Langfuse,
streaming subscriptions, and per-source-function call-site correlation
(`EG-M5C-7`, ADR-deferred).

**Normalization.** Langfuse trace/observation fields map to `TraceEnvelope` +
`EvalUnit`: trace id → `trace_id`, observation/generation id → `unit_id`,
input/output/messages/tools → `behavior`, model/usage → metadata, timestamps →
timing. Langfuse internal wrappers, cursors, and client/project objects are dropped
at the boundary and never reach the core.

**Failure handling.** Malformed payloads, auth failures, rate limits, timeouts,
empty pages, and pagination faults become a `langfuse_malformed_response` (or
sibling) `Diagnostic` and a `skipped`/`blocked` `LaneResult` — never a score or a
core `ScoreStatus.ERROR`.

**Deletion rule.** Deleting `adapters/trace_langfuse.py` leaves the required,
hermetic tier and the Phoenix/LangSmith connectors green (the registry resolves the
lane lazily; nothing on a required path imports it).

**Test policy.** Required proof runs hermetically over local stub fixtures with no
socket (`m5c.trace.langfuse_normalization`). A real pull is a **`live_lane`** smoke
test, skipped unless `EVALGLASS_LIVE_LANES=1` **and** the Langfuse env vars are set;
it is manual, secret-gated, and not required for ordinary CI.

## Consequences

- A host running Langfuse can import its traces as an opt-in `TRACE_SOURCE` lane;
  EvalGlass without the extra is unaffected and stays offline and SDK-free.
- Docs describe Langfuse support as an optional lane — never hosted telemetry, a
  required dependency, or certification.
