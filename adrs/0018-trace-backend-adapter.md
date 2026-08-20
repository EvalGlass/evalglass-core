# ADR 0018 — Trace backend adapter contract (stub-first)

- **Status:** accepted
- **Date:** 2026-05-31
- **Extends:** ADR 0006 (open-convention mapping), ADR 0017 (extension-lane framework)

## Context

A host eventually wants EvalGlass to read recorded behavior from a tracing backend
(Phoenix, Langfuse, …) rather than a local JSONL file. The risk is that a vendor
SDK or vendor span object leaks into the core/evaluators/Scorecard, or that the
required tier gains a network/SDK dependency (build contract §6 trace rule, §8).
M5a proves the *contract* before any real vendor work: the required tier stays
hermetic, and the backend attaches through the existing `TraceSource` port as a
deletable lane (ADR 0017).

## Decision

| Concern | Choice | Notes |
|---|---|---|
| First adapter | a **stub** backend (`adapters/trace_backend_stub.py`): the "backend response" is a local JSON file | No vendor SDK, no network this milestone; a real adapter replaces the read behind the same shape. |
| Boundary | the adapter maps only the response's `spans` → `TraceEnvelope`; any vendor wrapper/metadata (e.g. `_backend_internal`, `project_id`) is **dropped** | **No vendor object reaches** core/evaluator/RunRecord/Scorecard (proven by `check_envelopes_no_vendor_leak`). |
| Mapping | reuses the ADR 0006 open-convention span keys | One mapping, consistent with the conformance lane. |
| Failure | backend unavailable → `backend_unavailable`; malformed → `backend_malformed_response`; incomplete span → `trace_mapping_incomplete` — all typed `Diagnostic`s | A backend failure is diagnosed **separately from any metric score** (never a `0.0`). |
| Opt-in / deletion | no backend configured → `MissingPrerequisite` (skip); registered as the `trace-backend` lane; required tier imports it nowhere | Deleting the file leaves the local JSONL trace route intact (import-boundary guard + `verify-deletion`). |
| Dependencies | stdlib only; a real-vendor adapter adds a **pinned isolated extra**, never a required dep | ADR 0017 optional-dependency policy. |

## Consequences

- The backend-adapter contract is proven end-to-end without a vendor SDK or network;
  a real adapter is a drop-in replacement of the file read with an SDK/HTTP query.
- Vendor objects are normalized at the boundary and never enter the core-visible path.
- A backend outage is an honest diagnostic, not a fabricated low score.
- The lane is opt-in and deletable; removing it cannot change required-tier output.

## Alternatives considered

- **Build a real Phoenix/Langfuse adapter now.** Deferred — it adds an SDK and a
  network surface before the contract is proven; the stub proves the boundary and the
  failure taxonomy hermetically, and the real adapter is a deletable follow-up lane.
- **Let the backend return `TraceEnvelope`s directly.** Rejected — then the boundary
  is unprover; mapping vendor spans *inside* the adapter is exactly what proves no
  vendor object escapes.
- **Treat a backend outage as a low/zero score.** Rejected — infrastructure failure is
  not quality; it is a typed diagnostic, separate from scoring (build contract §8).
