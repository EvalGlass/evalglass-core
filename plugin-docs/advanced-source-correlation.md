# Advanced: per-source-function score views (design note — not built)

**Status:** advanced extension, **not built**. This note records the design and, more importantly,
the **non-coverage** it must declare. EGP-A1-7; ADR 0024 (score subject identity), ADR 0025.

## The three view granularities

| Granularity | What it groups by | Status |
|---|---|---|
| **per-metric** | metric name | shipped (`/evalglass view`) |
| **per-call** | a score's explicit subject identity (`example_id`/`unit_id`, framework slice F1) | shipped (`/evalglass view --by-call`) |
| **per-source-function** | the **discovered source call site** that produced the LLM call | **not built** (this note) |

## Why per-source-function is not available

Per-call grouping reads identity that already exists on each `Score` (F1). Mapping a score back to a
**source function** would additionally require a **trace↔call-site correlation** — a join across:

- the **candidate call sites** from discovery (`HostDiscoveryReport.llm_call_sites`, a *candidate
  inventory*, not a guarantee of finding every call),
- the **trace spans** in the `TraceEnvelope`,
- the `EvalUnit` identity, and the `Score` subject identity.

**That correlation does not exist** — there is no reliable link from a trace span to the exact
source function today. Inventing one (e.g. by name-matching or order) would be exactly the
false-confidence the project forbids.

## If it is ever built

- It depends on F1 (done) **and** an explicit, evidence-backed correlation layer — never a guess.
- Every correlated score must carry a **confidence label**; uncorrelated spans get a **diagnostic**,
  not a silent attribution.
- The view must state plainly that discovery is a **candidate inventory** and that uncorrelated
  calls are **not covered** — it grants no authority and makes nothing "pass".

Until then, `view --by-call` (per explicit subject identity) is the honest ceiling.
