# ADR 0033 — Live trace-connector boundary and optional provider-SDK policy

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** remaining product plan `jira_tickets_remaining_implementation_plan.xlsx` epic EG-R0 (stories EG-R0-1 … EG-R0-7); `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §0.6 / §M6-S6–S8; `docs/M6_TICKET_CORRECTIONS.md` C1–C2
- **Related:** [0017](0017-extension-lane-framework.md) (extension-lane framework + optional-dependency policy), [0018](0018-trace-backend-adapter.md) (trace backend adapter, stub-first), [0006](0006-open-convention-trace-mapping.md) (open-convention trace mapping), [0016](0016-optional-live-judge-lane.md) (optional live-judge lane — the lazy-egress exemplar), [0031](0031-runner-attach-seam-and-lane-results.md) (runner-attach seam + `RunRecord.lane_results`)
- **Provider ADRs:** [0034](0034-langfuse-trace-connector.md) (Langfuse), [0035](0035-phoenix-trace-connector.md) (Phoenix), [0036](0036-langsmith-trace-connector.md) (LangSmith)

## Context

The hermetic foundation tranche (EG-H0 … EG-H5) deliberately **deferred** the
SDK-backed live tracing connectors: `EG-M5C-6` stayed `not_started`, the
optional extras stayed empty, and `tests/test_dependency_budget.py` *banned* any
provider/observability SDK from the runtime dependencies, the optional extras,
and `uv.lock` (`docs/M6_TICKET_CORRECTIONS.md` C1/C2). The connector contract was
proven only over the shipped `StubBackendTraceSource`
(`tests/adapters/test_trace_connectors.py`).

The remaining tranche (EG-R0 … EG-R5) builds the three real connectors — Langfuse
(EG-R1), Phoenix (EG-R2), LangSmith (EG-R3) — so a host can import recorded traces
from a tracing backend it already runs. That **reverses the zero-new-dependency
rule** for these three packages, but only as *opt-in, isolated, pinned* extras
that never touch the required import path. Because this changes the dependency
surface, the optional-extra policy, the import-boundary guard, and the public lane
roster, it is recorded here (cross-cutting) and in one ADR per provider before any
code lands.

The hard constraint is the same one that governs every extension lane, stated
sharply for connectors:

> **A connector imports EVIDENCE, never AUTHORITY.** A provider pull that
> succeeds produces normalized `TraceEnvelope`/`EvalUnit` input records and a
> `LaneResult`; it can never make the `Scorecard`, verdict, authority, or CI exit
> any stronger than the same run with the connector absent.

## Decision

**1. Each provider SDK is an opt-in, pinned, isolated optional extra — never a
runtime dependency.** `project.dependencies` stays PyYAML-only. Each connector
declares its package under its **own** `[project.optional-dependencies]` extra
(`langfuse-trace`, `phoenix-trace`, `langsmith-trace`); the package and pin land
in `pyproject.toml` and `uv.lock` in EG-R0-2 after the provider ADR is accepted.
Installing EvalGlass without an extra neither imports nor requires that provider.

**2. The SDK is imported lazily, inside the lane-local call path only.** No
provider package is imported at `import evalglass` time, at `runner`/`core`/
`harness` import time, or even at connector-module import time. The SDK is
imported inside the connector's client factory / `read()` path (the pattern the
live-judge lane established with stdlib `urllib`). The connector module is
therefore importable for metadata, deletion, and mapping tests **without the extra
installed**; a missing extra surfaces only when the lane is *enabled and resolved*,
as a typed `MissingPrerequisite` skip — never an `ImportError` crash.

**3. The import boundary is guard-enforced, fail-closed.** `langfuse`,
`langsmith`, and the Phoenix client distribution join the forbidden-import set in
`check_no_provider_sdk`; only the three provider adapter files are allow-listed
(alongside the existing `judge_live.py` / `score_sink_dashboard.py` stdlib-egress
exemptions). A synthetic provider import in `runner.py`, the core, or any non-lane
adapter is detected and fails the required tier. The runtime *import closure* stays
SDK-free even though the optional *extras* now name SDKs (EG-R0-5).

**4. Credentials and endpoints are host-owned, opt-in, and never persisted.**
Provider lane options carry an endpoint, a project/query selector, an optional time
window and limit, credential **environment-variable references** (never literal
secrets), and a `data_policy`. Credentials are read only when the lane is enabled.
A secret value never appears in `RunRecord.lane_results`, `Scorecard`, reports,
logs, or evidence packs. The `DataPolicy` egress gate is checked **before** any
live client call (EG-R0-4); `forbidden`/`missing`/`unknown` blocks egress with no
connect attempt.

**5. The connector normalizes at the boundary; only `TraceEnvelope`/`EvalUnit`
cross it.** Provider spans/runs are mapped to vendor-neutral records; vendor
wrapper objects, cursors, client objects, and project objects are dropped at the
adapter and never reach the core, evaluators, `RunRecord`, or `Scorecard`. Malformed
responses, auth failures, rate limits, timeouts, empty pages, and pagination faults
become stable typed `Diagnostic`s and a `skipped`/`blocked` `LaneResult` — never a
`Score`, a `ScoreStatus.ERROR` in the core, or a fabricated passing measurement.

**6. Live access is `live_lane`-only and never required.** Required CI runs
`pytest -m 'not live_lane'` with the egress guard armed and proves each connector
over **local stub fixtures with no socket**. A real provider pull is a
`live_lane`-marked smoke test, double-guarded by `EVALGLASS_LIVE_LANES=1` **and** the
provider's own endpoint/credential env vars; it is manual, secret-gated, and not a
merge requirement (EG-R0-6).

**7. Connectors stay deletable.** Each connector lane resolves lazily through the
registry; deleting one provider adapter file leaves the required, hermetic tier and
the other providers green (EG-R0-5 deletion-invariance tests).

**8. `EG-M5C-6` flips to `covered` only when all three connectors prove their
scenario** (`m5c.trace.langfuse_normalization`, `m5c.trace.phoenix_normalization`,
`m5c.trace.langsmith_normalization`) under the single-row rule (EG-R4-2). Partial
implementation cannot satisfy `--require-complete` by marking the row optional.

## Consequences

- A host can import live traces from Langfuse / Phoenix / LangSmith as opt-in lanes,
  while the required tier stays offline, SDK-free, and byte-identical in its verdict
  surface — a connector adds rows to `RunRecord.lane_results` and nothing else.
- The dependency budget guard is *relaxed in one specific way* (EG-R0-2): the three
  named connector extras may pin their SDK, but `project.dependencies` and the
  runtime import closure stay SDK-free. The guard still fails on a provider SDK in
  required dependencies or a non-allow-listed import.
- Public surfaces (lane roster, status registry, docs) gain three `planned`,
  `TRACE_SOURCE` lanes. Capability-status words remain roadmap metadata, never a
  verdict/score/authority/exit token.
- This boundary is provider-independent; each provider ADR (0034/0035/0036) records
  only the package selection, credential shape, query scope, and mapping specifics.
- If a future change ever let a connector result influence the verdict, authority,
  exit, or report headline — or made a provider SDK a required dependency — that
  reverses this ADR and requires a new ADR superseding it.
