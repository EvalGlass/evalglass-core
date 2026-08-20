---
name: evaluate-an-agentic-app
user-invocable: false
description: >-
  Entry point when a user asks to evaluate their agentic app / LLM calls with EvalGlass, or to
  measure, score, or set up evaluation for an AI app — in natural language, without naming a verb.
  Routes the request into the /evalglass umbrella and the right backing skill; it orients and
  hands off, and never silently mutates files, runs evaluations, or makes anything gate.
---

# Evaluate an agentic app (natural-language entry)

Triggers when someone says things like *"evaluate my agentic app with EvalGlass"*, *"set up evals
for this LLM app"*, *"measure the quality of these LLM calls"*, or *"score this app's outputs"* —
without typing a `/evalglass` verb. Your job is to **orient and route**, not to do the work
silently.

> EvalGlass is an AI-safety instrument. It measures and surfaces honest signal; **the host decides
> what counts as correct and what may gate.** You never make a run "pass".

## What to do

1. **Read state first** (the same honest dashboard as bare `/evalglass`): is the runtime vendored
   (`evals/_evalglass/`)? Any datasets/traces? Any approved authority? Say what's true; guess
   nothing.
2. **Name the next honest step** and route to the matching verb + backing skill — do not perform a
   mutating step without the user's go-ahead:
   - not integrated yet → **`/evalglass setup`** (`installing-evalglass`): discover candidate call
     sites (announced, read-only, consent-gated; resolve data-policy with the host), then vendor +
     scaffold `proposed` assets.
   - have the runtime, need data → **`/evalglass connect`**: import exported OTel/OpenInference or
     local trace JSON, or scaffold a `proposed` dataset.
   - no metric set yet → **`authoring-a-metric`**: the host decides which checks the app needs and
     the agent scaffolds each as a `MetricSpec` (runtime / reference / judge tiers) into
     `evals/evalglass.yaml` — every asset stays `proposed`/`uncalibrated`; the host validates.
     EvalGlass is the framework, not the oracle: you name the check, it supplies the machinery.
   - ready to measure → **`/evalglass run`**, then **`/evalglass view`** / **`/evalglass explain`**
     (`reading-a-scorecard`).
   - want a quick, honest demo first → **`/evalglass run --example quickstart`** (the bundled
     example) — it produces real non-reference signal and an honest **informational** verdict.
3. **Set expectations honestly.** A first run is **informational** by design: it shows real
   deterministic signal (e.g. is each output well-formed / are required fields present) with no
   gold and no calibration — useful, but **not** a quality pass. Gating requires the host to
   validate gold, approve a threshold, and calibrate judges.

## Advanced connectors (v1.1) — opt-in, deletable, never authoritative

These extend `connect` and are **not** part of the v1 required journey; offer them only when asked.

- **`connect --live <platform>`** — a **wired, opt-in verb** (ADR 0046) that scaffolds a live-platform
  trace connector into `evalglass.yaml`, so a following `run` pulls the traces. `connect --live
  langfuse|phoenix|langsmith` writes/enables the matching **opt-in, experimental**, deletable
  `TRACE_SOURCE` lane with
  **credentials as env-var NAMES** (never literal secrets — a literal is rejected and never echoed),
  a **fail-closed** `data_policy` (defaults to `unknown`: egress is refused until you consciously set
  `permitted`), and the note that a live pull forces `proposed`. Rules: the verb writes config only
  and imports **no provider SDK** and no `adapters/trace_*` module; the lane is **isolated and
  deletable** (removing it leaves required local workflows byte-identical); absent prerequisites
  (endpoint/credentials/extra) **skip cleanly** rather than failing a run; and a live-connected run is
  `proposed` — it **cannot gate**. The real Phoenix/Langfuse/LangSmith connectors sit behind isolated,
  pinned **optional extras** (`phoenix-trace`/`langfuse-trace`/`langsmith-trace`) the host installs
  deliberately. This is distinct from the hermetic v1 `connect` verb, which imports *exported*
  OTel/OpenInference JSON and touches no network.
- **`connect --synth`** — synthetic-data generation is **not built**; there is no generator. Say so
  plainly (the honest governance truth). If a generator is added later, generated data is imported
  as **`proposed`** and is **never** presented as validated gold — only a host validates it.
- **Per-source-function views** (a score → its source call site) are an advanced, **unbuilt**
  extension — see
  [`plugin-docs/advanced-source-correlation.md`](../../plugin-docs/advanced-source-correlation.md).

None of these grant authority or make a run "pass".

## Never

- Never silently write config, vendor files, wire CI, or mutate baselines — every such act is
  explicit and user-invoked.
- Never describe the result as "passing", "safe", or "correct"; the **`evalglass-honesty`** skill
  governs how you report.
- Never assume a data-policy answer; never populate the host's authority records.
