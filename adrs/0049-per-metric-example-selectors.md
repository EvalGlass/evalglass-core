# ADR 0049 — Per-metric example selectors (`applies_to`)

**Status:** Accepted

## Context

By default every metric scores every example (the M1 route-convergence model). On a single-call-site
app that is correct. On a **multi-call-site** app (many distinct LLM workflows, each with its own
output schema) run as one flat pass over a heterogeneous record stream, it cross-contaminates:

- a metric drafted for one call site's schema also scores records of other call sites;
- field-name collisions cause **false attribution** (a bounds metric keyed on `confidence` reports a
  value computed from a *different* workflow's outputs);
- records of a schema absent from the stream drag `field_presence`/bounds metrics toward misleading
  lows (a genuine `scored 0.0` that reads like a quality failure but is a *routing* artifact);
- N schemas yield N identical `structural_shape` rows.

This was surfaced by two independent field evaluations of a scaffolded metric suite on a real
LangGraph/LiteLLM app. It does not breach honesty (everything stays `informational`; `non_evaluable`
is excluded, not zeroed) but it makes the Scorecard actively misleading to read.

## Decision

Introduce an optional, host-owned **`ExampleSelector`** (core) that restricts a metric to the
examples whose own `Example.metadata` satisfies host-declared constraints. A metric declares it in
config via `applies_to: {metadata_key: value | [values]}`; the harness builds the selector and threads
it onto `MetricPlan.selector`; the core `_collect` scores only matching examples.

**Strictly generic (CLAUDE.md — "generic by contract").** The mechanism keys only on host-declared
`metadata`. EvalGlass assumes **no** specific key or value and infers none from any app, domain, or
tracing convention. How an example acquires that metadata is host/vendor-specific and already flows in
(`example_from_trace` carries `TraceEnvelope.metadata` onto `Example.metadata`) — an OTel span name, a
Langfuse observation name, arbitrary trace tags, or a dataset field. A scaffolded metric therefore
does **not** hardcode any per-workflow tag; the agent emits a working flat config by default and
documents the `applies_to` binding as a host-owned seam.

## Honesty rules (fail-closed)

1. **Fail-closed match.** An example matches only if *every* constrained key is present with an allowed
   value. An absent key is a non-match — a selector can only *narrow* a metric's population, never
   silently widen it.
2. **Empty match is visible, never vacuous.** A selector that matches no example yields a single
   `non_evaluable` score carrying a `selector.no_match` diagnostic (never a `0.0`, never a silent
   absence). Its aggregate value is `None`, so an active gate over it **blocks** (`no_measured_value`)
   rather than passing on no evidence.
3. **Integrity bypass.** The run-integrity example the harness injects when input is unreadable is
   flagged with the reserved `INTEGRITY_METADATA_KEY` and **always** matches every selector — so an
   incomplete-input run still blocks an active gate, even a selector-scoped one.
4. **Provenance.** The selector enters the run's gating `authority`/`config` provenance dimension, so
   an `applies_to` change breaks baseline comparability (it changes which records a metric scored).

## Backward compatibility

`applies_to`/`selector` are optional and default absent. A run with no selectors is **byte-identical**
to the pre-selector engine: `MetricPlan.selector is None` → every example scored, exactly as before.
`ExampleSelector` is a frozen, effect-free, JSON-serializable core dataclass (stdlib-only).

## Consequences

- A single run of a mined multi-call-site suite over a metadata-tagged stream produces a **per-call
  site** Scorecard — each metric scores only its own workflow — instead of cross-attributed numbers.
- The Verdict Engine is unchanged: a selector only changes *which* scores a metric has; verdict,
  authority, and exit mapping are computed exactly as before from the resulting scores.
- New public surface: `ExampleSelector`, `INTEGRITY_METADATA_KEY` (core), `MetricPlan.selector`,
  `MetricConfig.selector`, and the `applies_to` config key.
