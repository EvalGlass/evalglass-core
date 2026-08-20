# ADR 0036 — LangSmith trace connector

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** remaining product plan `jira_tickets_remaining_implementation_plan.xlsx` epic EG-R3 (EG-R3-1 … EG-R3-6); `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §M6-S8
- **Related:** [0033](0033-live-trace-connector-boundary.md) (cross-cutting connector boundary — governs everything below), [0018](0018-trace-backend-adapter.md), [0006](0006-open-convention-trace-mapping.md)

This ADR records only the **LangSmith-specific** decisions. The optionality, lazy
import, credential-handling, egress, normalization, deletion, and `live_lane`
rules are defined once in **ADR 0033** and inherited here.

## Decision

**Package and extra.** The connector uses the official **`langsmith`** PyPI
distribution (the LangSmith client), declared under the optional extra
**`langsmith-trace`**. It is never a runtime dependency. The exact pin is finalized
in `pyproject.toml`/`uv.lock` in EG-R0-2; this ADR fixes the package selection and
its optionality.

**Why optional, and the LangChain caveat.** LangSmith is one tracing backend among
several; EvalGlass runs fully without it. The connector imports **only** `langsmith`,
not `langchain` / `langchain-core` — no LangChain package may enter EvalGlass's
required *or* optional import path. The required-tier import-boundary guard (EG-R0-5)
enforces this.

**Lazy import boundary.** `langsmith` is imported **lazily**, inside the connector's
client factory / `read()` path only — never at module import time. Importing
`evalglass`, the runner, or `adapters/trace_langsmith.py` succeeds without the
`langsmith-trace` extra; a missing extra becomes a typed `MissingPrerequisite` skip
when the lane is enabled, never an `ImportError`.

**Credential model.** Credentials are host-owned **environment-variable references**,
read only when the lane is enabled: `LANGSMITH_API_KEY` and `LANGSMITH_ENDPOINT`
(API URL). Literal secrets are never accepted in config and never written to
`RunRecord.lane_results`, `Scorecard`, reports, logs, or evidence packs.

**Supported query scope.** A single read selects a LangSmith project plus an optional
time window and run limit (e.g. `client.list_runs(project_name=..., limit=...)`),
paginated by the client iterator/cursor. Out of scope: writing/annotating LangSmith,
dataset/experiment management, and per-source-function call-site correlation
(`EG-M5C-7`, ADR-deferred).

**Normalization.** LangSmith run/span fields map to `TraceEnvelope` + `EvalUnit`:
run trace id → `trace_id`, run id → `unit_id`, inputs/outputs/messages/tools →
`behavior`, model/usage → metadata, start/end times → timing. LangSmith internal run
objects, cursors, and client/project objects are dropped at the boundary and never
reach the core.

**Failure handling.** Malformed payloads, auth failures, rate limits, timeouts,
empty pages, and pagination faults become a `langsmith_malformed_response` (or
sibling) `Diagnostic` and a `skipped`/`blocked` `LaneResult` — never a score or a
core `ScoreStatus.ERROR`.

**Deletion rule.** Deleting `adapters/trace_langsmith.py` leaves the required,
hermetic tier and the Langfuse/Phoenix connectors green (the lane resolves lazily;
nothing on a required path imports it).

**Test policy.** Required proof runs hermetically over local stub fixtures with no
socket (`m5c.trace.langsmith_normalization`). A real pull is a **`live_lane`** smoke
test, skipped unless `EVALGLASS_LIVE_LANES=1` **and** the LangSmith env vars are set;
it is manual, secret-gated, and not required for ordinary CI.

## Consequences

- A host using LangSmith can import its runs as an opt-in `TRACE_SOURCE` lane;
  EvalGlass without the extra is unaffected and stays offline and SDK-free.
- Restricting the import to `langsmith` (never LangChain) keeps the optional footprint
  bounded and prevents a large ecosystem from leaking onto any EvalGlass path.
- Docs describe LangSmith support as an optional lane — never hosted telemetry, a
  required dependency, or certification.
