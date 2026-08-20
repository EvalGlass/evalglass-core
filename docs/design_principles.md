# EvalGlass — Design Principles

> **Status:** Draft v4 · **Date:** 2026-05-27
> **Scope:** Foundational design principles for EvalGlass, an open-source, embeddable evaluation **framework** for agentic AI projects, **delivered as a Claude Code / Codex skill** that installs and integrates the runtime into a host repo.
> **Supersedes:** v3 (2026-05-22). v4 aligns the principles with the architecture contracts: the Evaluation Core is effect-free and owns meaning; the Runtime Harness owns effects; the Verdict Engine is the only verdict path; Scorecard / RunRecord JSON are primary; authority, baseline comparability, and provenance are typed claims; and datasets, traces, subprocess replay, and future routes converge into common evaluation units.

---

## 0. Purpose and how to read this document

This document defines the **design principles** of EvalGlass: the durable tenets that constrain and guide every architecture and implementation decision that follows. It is written *before* the architecture on purpose, so that the architecture can be derived from a stable, explicit value system rather than assembled ad hoc.

A principle here is **a tie-breaker, not a feature and not an architecture decision.** When a design choice is ambiguous, the relevant principle — and, where principles conflict, the precedence order in §6 — decides it. Principles should change rarely; architecture and implementation should change freely beneath them.

These principles deliberately stop short of architecture. They commit to *directions* (route convergence, trace capability, ports, pure-function evaluators, delivery as a skill) but not to *mechanisms* (which database, which language, the skill's internal layout). §7 lists, explicitly, what they leave open for the architecture phase to decide.

**Audience:** the architects and implementers of EvalGlass, the engineers in host projects who inherit and extend it, and the AI coding agents that install and wire it in (P13).

---

## 1. North Star

> **EvalGlass lets a small-to-medium agentic project measure and improve the quality of its LLM calls with minimal ceremony, and grow that capability as its needs deepen.**

Four commitments fall out of that sentence and govern everything below:

- **Generic** — EvalGlass knows nothing about any one domain; it is inherited and customised per host project.
- **Minimal and expandable** — the irreducible core is tiny; capability is added in rings, never forced.
- **Trustworthy** — a measurement you cannot trust is worse than no measurement; correctness of the evaluation itself and honesty of the verdict outrank breadth.
- **Open and skill-delivered** — open source, delivered as a Claude Code / Codex skill that installs and integrates the runtime into the host repo, with no lock-in.

**Division of expertise.** EvalGlass requires **domain judgment** — knowing what counts as a correct output in the host's domain — but it does **not** require AI-evaluation or AI-safety expertise. That expertise lives in the framework and its skill. A team that knows its own domain, but has never built an evaluation, can adopt EvalGlass by asking a coding agent to do it.

**What it is for.** Three concrete purposes justify the design choices throughout:

1. **Spot issues** — fast quality assessment that surfaces problems early (P9, diagnose).
2. **Catch regressions in PR review** — an honest quality gate on pull requests, in CI (P9, P12).
3. **Inform optimisation** — feed signals that the host uses to improve its agentic system (P16).

EvalGlass is an **instrument**, not a product. It measures and surfaces; the host project acts.

---

## 2. Identity and scope

### P1 — Framework, not platform

EvalGlass is a **framework**: it owns the evaluation lifecycle and defines the contracts; the host project inherits it and fills the extension points (domains, schemas, evaluators, rubrics, taxonomy). This is inversion of control — EvalGlass calls the host's plugged-in pieces, not the other way around. It may ship batteries-included services (a default store, a runner, optionally an annotation surface), but those are conveniences around the framework, never a standalone hosted system the user logs into.

*Why.* "Inheritable by many projects, customised internally" is only achievable through inversion of control. A platform would impose its own world; a framework lends structure and steps aside.

*Implications.* The deliverable is a dependency a project adds, not a server it integrates with. It is a framework **delivered as a skill** (P13): the skill is the delivery and integration vehicle; the framework is the runtime it installs. Extension points are first-class, typed, and documented. Bundled services are optional and replaceable.

### P2 — Open source, skill-delivered, built to be inherited

EvalGlass is **open source**, and the framework is the **runtime** that its skill installs into a host repo by **vendoring the minimal source in** — not a hosted service and not, primarily, a published package you install as a black-box dependency. Its public contracts — the core types, the evaluator protocol, the ports, and the run configuration — are stable, semantically versioned, documented, and minimal-dependency, so a project can vendor, adapt, and extend it without friction or lock-in.

*Why.* Distribution-by-vendoring keeps the runtime editable and adaptable in place (which a published package resists) and removes release ceremony. Vendoring also serves minimalism (P3): the skill copies only the subset a project needs. Lock-in directly contradicts the inheritance model (P1).

*Implications.* The public repo is the source of truth; the skill fetches a pinned version and vendors the minimal core into the host's convention. Once installed, the runtime runs on its own, with no dependency on the skill, the coding agent, or any external service (P13 boundary). Dependency-light core with rings behind optional extras. Semantic versioning of the public API as a hard commitment (many repos vendor it). A permissive licence to maximise adoption. No telemetry or phone-home — the framework runs entirely inside the host's environment. The pinned version is recorded in the host repo so re-vendoring and upgrades are reproducible (P14).

### P3 — Minimal core, designed for extension

The core is the **absolute minimum that delivers value**: take normalized host behaviour, evaluate it against gold and/or non-reference checks, produce typed scores and diagnostics, resolve authority and provenance, and return a typed Scorecard / RunRecord with a verdict from one Verdict Engine. Everything else — synthetic data generation, an annotation UI, observability adapters, trajectory evaluation, multi-backend integrations, live-provider lanes — is an **expansion ring** layered on the core without modifying it.

*Why.* The smallest possible adoption must be trivial: bring a JSONL gold set, register two evaluators, run, read the Scorecard. The core's job is not to have features; it is to define measurement meaning cleanly enough that rings attach without refactoring (open for extension, closed for modification).

*Implications.* When unsure whether something belongs in the core, it does not. The core may define contracts, score states, aggregation, authority, provenance, baseline comparability, and verdict rules; it must not perform I/O, call models, render reports, or depend on optional rings. Adding a ring is additive configuration, not core surgery. The skill vendors only the subset the project needs (P2). Sensible defaults make the smallest adoption trivial, and every default is overridable.

### P4 — Generic by contract, specific by configuration

The framework contains **zero domain knowledge.** All domain specificity — output schemas, content rules, scenario libraries, the metric taxonomy, the evaluators and their rubrics, what "good" means — enters exclusively through typed extension points supplied by the host project. The spine is domain-agnostic; the leaves are domain-specific.

*Why.* Genericity is what makes EvalGlass inheritable. Any domain assumption baked into the core would silently narrow the set of projects it can serve.

*Implications.* No hardcoded metric set, no fixed schema, no built-in notion of any particular task. Reasonable *defaults* are allowed; domain *assumptions* are not. The framework can ship reference evaluators that are genuinely domain-neutral (structural validity, field presence, set overlap); anything that encodes domain meaning is host-supplied. The typed extension points are not only a human contract — they are the surface the skill's coding agent reads and fills (P13), so they must be self-describing.

### P5 — Serve small-to-medium agentic projects, and know where you stop

The target is the broad middle: agentic projects for which **evaluating individual LLM calls already goes a long way.** The default unit of evaluation is the LLM call. Richer agentic evaluation — full trajectories, tool-selection correctness, multi-turn state, cross-agent coordination — is a named expansion, not a core obligation. The most complex multi-agent systems will need more core than EvalGlass should carry, and that is acceptable.

*Why.* Trying to serve every agentic system would bloat the core and betray P3. An honest, stated boundary is more useful than an over-promise.

*Implications.* Per-call evaluation is the floor and must be excellent. Trajectory/step evaluation is the first major expansion and the line beyond which EvalGlass stops claiming fit. The architecture must not paint the core into a corner that forbids that expansion (see P10: building on traces keeps the door open), but it need not deliver it on day one.

---

## 3. The nature of evaluation

### P6 — Pure evaluators, effect-free core, effectful runtime

An evaluator is a pure function of the form `(example, context, evidence) → score(s)`. It performs no I/O, holds no connection to any vendor, and — wherever the metric allows — is deterministic. The Evaluation Core around it is also effect-free: it validates score semantics, aggregates, resolves authority, checks baseline comparability, records provenance, and asks the Verdict Engine for the result. Datasets, stores, runners, trace sources, judge models, verifiers, reports, and dashboards are Runtime Harness concerns around this core.

*Why.* Pure evaluators and an effect-free core are what make EvalGlass trustworthy and portable. The same evaluator and core contracts can run unchanged against gold in CI, recorded traffic in an audit, sampled live traffic online, or deterministic fixtures in the test system.

*Implications.* The evaluator interface and core contracts are the most carefully designed surfaces in the system. Side effects (calling a judge model, querying an external verifier, loading traces, reading files) are performed before the core sees data and are passed in as evidence. Vendor SDKs, clocks, randomness, filesystem access, subprocesses, network calls, and report rendering stay outside the core.

### P7 — Two complementary lenses: reference and non-reference

Quality is always viewed through two lenses. **Reference-based** evaluation compares output to a gold standard — *is this correct?* **Non-reference** evaluation (deterministic checks and LLM-as-judge) assesses output using only its input and itself — *is this grounded, faithful, well-formed?* Neither is sufficient alone, and the **divergence between them is itself a diagnostic** (correct-but-ungrounded indicates fragility; grounded-but-incorrect indicates a prompt/schema problem).

*Why.* This distinction is intrinsic to whether a ground truth is at hand, and it is independent of where the evaluation runs. At inference time on a never-seen input, only non-reference evaluation is possible.

*Implications.* The framework must support both lenses as first-class and make their disagreement legible. A host project may start with non-reference only (no gold required) and add reference metrics once it has gold — the framework must not assume gold exists.

### P8 — A trustworthy eval beats a comprehensive one

The dangerous failure mode of an evaluation system is **false confidence** — a green scorecard that does not mean what it claims. EvalGlass therefore prefers a few calibrated, hard-to-game signals over many noisy ones. Score value, measurement validity, authority, and baseline comparability are distinct typed facts. A metric **earns the right to gate**: variance is established over multiple runs before a threshold is set, and a judge is calibrated against human judgment before its scores are believed. Uncalibrated, unstable, unauthorized, policy-forbidden, or non-comparable measurements are *informational* or *blocked*, never silently green.

*Why.* An eval you cannot trust is worse than none, because it licenses bad decisions with a veneer of rigour. As a safety instrument, EvalGlass must be honest about what it does and does not know.

*Implications.* Threshold-setting is variance-aware by design (record spread before gating). Judge metrics carry a calibration status and cannot gate until calibrated. Baseline deltas require comparable provenance. Metric design actively avoids loopholes (e.g., grounding checks an output can satisfy without being grounded). "Absence of a failing score" is never presented as proof of correctness or safety. **This discipline outranks the convenience of a frictionless, skill-driven setup.** A skill may scaffold candidate gold and propose thresholds, but neither carries authority: proposed thresholds stay informational until approved, and candidate gold stays provisional until the domain expert validates it (P15). Skill-assisted setup is never a backdoor around calibration or domain validation — it ends in a guided confirmation, never a silent green check.

### P9 — Diagnose, don't just score

A score that says only "0.62" is nearly useless. Metrics must **localise where and why** quality is what it is. The framework embodies a diagnostic order — structural validity first (if the output won't parse, nothing else is meaningful), then correctness (where it diverges from gold), then quality (why). A regression should point at a cause, not just a number.

*Why.* The purpose of evaluation is to enable improvement (P16) and to spot issues fast (Purpose 1). A signal that cannot be acted on serves neither.

*Implications.* Evaluators emit not just a value but enough structure (which field, which claim, which step) to be actionable. The framework supports per-granularity scoring so a failure can be traced to its source rather than averaged into invisibility. In PR review (Purpose 2), the diagnostic detail is what turns a red gate into an actionable review comment.

---

## 4. Integration and execution

### P10 — Route-convergent, trace-capable

EvalGlass accepts host behaviour through multiple routes — JSONL datasets, recorded traces, subprocess replay, direct core fixtures, and later online or backend integrations — but those routes must converge into common evaluation contracts. Traces remain the strategic integration seam for richer agentic behaviour, but the MVP must not require a host to adopt a tracing backend.

*Why.* Small projects need a local JSONL path first; growing projects need trace import and backend adapters later. A route-convergent design gives both groups the same measurement semantics. Building on normalized traces also keeps the door open to trajectory evaluation (P5): a trajectory is simply a larger slice of observed behaviour.

*Implications.* Dataset replay, trace import, subprocess replay, and future adapters all normalize into declared evaluation units (call first; step, trajectory, and session later). Trace adapters should align with open conventions (e.g., OpenTelemetry / OpenInference) so backend integrations are thin. The framework does not require the host to adopt a particular tracer, backend, or observability product.

### P11 — Backend-neutral through ports; ship humble defaults

EvalGlass depends on **abstractions, not vendors**: trace source, dataset store, score sink, judge model, external verifier, annotation store. Any specific backend (a tracing platform, a database, a model provider) is an adapter behind a port. The framework ships the simplest defaults that make the core usable out of the box; every default is swappable.

*Why.* Lock-in contradicts genericity and the open-source inheritance model (P2). But minimalism (P3) means the core may ship a single concrete default (e.g., one local store) rather than many adapters. The *interface* is the principle; the *multi-backend* is an expansion ring.

*Implications.* No vendor SDK appears in the core's control flow. The first release may support exactly one store and one judge-model route — but behind interfaces, so the second is additive. "Integrate with Langfuse/Phoenix/LangSmith" means "implement the trace-source (and optionally score-sink) port," nothing more.

### P12 — Placement is policy, not topology

*Where* a metric runs — inline in the request path, asynchronously on sampled traffic, or offline in batch — is decided by its **profile** (`needs_gold`, `needs_llm`, latency, cost, data-policy), not by hardcoded deployment topology. An air gap is simply the most restrictive setting of the data-policy attribute, not a structural assumption the framework is built around.

*Why.* Conflating "can this run in production" with "should this run inline" produces brittle, deployment-specific designs. Separating availability from cost/latency/governance lets the same evaluator serve every mode.

*Implications.* The metric model carries a profile; a router/harness places each metric accordingly. **Offline-batch is the MVP execution mode, and its primary consumption context is PR review / CI** — a regression gate on pull requests is the headline use case (Purpose 2). Inline and async are expansions sharing the same evaluators. Data-governance constraints (PII, egress limits, which model may see what) are configuration on traces/datasets/metrics, read at routing time — not branches in the code.

### P13 — Delivered as a skill that installs and integrates the runtime

EvalGlass is a framework **delivered as a skill** for AI coding agents (Claude Code, Codex). The skill installs the runtime into the host repo, integrates it with the host's LLM calls, and adapts it through the extension points — by reading the repo and following its own recipe. The skill **encapsulates the evaluation and AI-safety expertise**, so the host needs none. Predictable structure beats maximal configurability.

*Why.* The customisation bridge is a coding agent running a skill, not a human reading docs. An extension surface that is ambiguous, convention-poor, or full of hidden magic gets wired in badly — and a badly wired eval is a trust hazard (P8). Delivering the framework as a skill is what reduces adoption to a single sentence ("implement evaluation of this project using EvalGlass") for a team with domain knowledge but no evals expertise.

*Implications.* The skill is the primary delivery and integration vehicle: it fetches a pinned framework version, vendors the minimal core into the host's convention, scaffolds config / evaluators / datasets / rubrics, wires the CI gate, and enforces the trust guardrails (P8). Convention over configuration, with predictable, repo-recognisable structure. Typed, introspectable contracts (so the agent can read the API), examples as first-class artefacts, and no behaviour that depends on undocumented conventions. Documentation is interface: the skill is the agent's instruction set, and it carries the evaluation and AI-safety know-how the host lacks.

*Boundary.* The skill and the coding agent are **integration-time** only. Once installed, the vendored runtime runs on its own — in CI and beyond — with no dependency on the skill, the agent, or any service (see Non-goals, §8). And skill-assisted setup never gates on uncalibrated thresholds or unvalidated domain ground truth (P8, P15).

---

## 5. Lifecycle and purpose

### P14 — Versioned and reproducible, with provenance on every score

Datasets, traces, prompts, rubrics, evaluator code, calibration records, baseline records, the pinned framework version, model and prompt versions, policies, and thresholds are all version-controlled or fingerprinted. Every score, Scorecard, and RunRecord carries the provenance needed to interpret it — what was evaluated, against what reference or evidence, by which evaluator version, under which model/prompt/configuration, and against which comparable baseline if a regression claim is made. Deterministic evaluators produce identical scores on identical inputs.

*Why.* A score without provenance is uninterpretable, and a regression cannot be diagnosed (P9) if you cannot say what changed. Trust (P8) depends on reproducibility. PR review (Purpose 2) depends on comparability across commits.

*Implications.* Prompts and rubrics live in the host repository, never only inside a vendor UI. The pinned framework version is recorded so the skill can re-vendor or upgrade reproducibly (P2). The store records configuration alongside values. Runs are comparable only when the relevant fingerprints match; otherwise EvalGlass must report non-comparability instead of manufacturing a regression claim.

### P15 — Domain judgment is the anchor; evaluation expertise is the framework's

The host must supply **domain judgment** — what counts as a correct output in its domain — and must confirm gold, rubrics, calibration records, baseline choices, and gating thresholds before they carry authority. It needs **no AI-evaluation or AI-safety expertise**: the methodology of evaluation — which metrics to use, how to calibrate, the trust discipline, the safety guardrails — lives in the framework and its skill. Where annotation is used it is structured (explicit scoring, an acceptance gate, mandatory failure attribution), but the **minimal core works with bring-your-own-gold** and no annotation tooling.

*Why.* Only the domain expert knows whether an output is correct, and that judgment cannot be delegated to the framework without manufacturing false confidence (P8). But the *methodology* of evaluation is exactly what a non-expert team lacks — and exactly what EvalGlass and its skill supply.

*Implications.* Ground truth (gold), rubrics, approved thresholds, calibration, and baselines are host-owned truth artifacts even when the skill scaffolds them. The skill-driven setup ends in a short, plain-language confirmation step, not a silent gate. Calibration of judges against human (domain) judgment is supported and recommended. The annotation surface is an expansion ring, not a precondition.

### P16 — EvalGlass measures and feeds back; the host improves

The framework's job is to **measure quality and surface signals**, including feeding failure patterns back toward dataset growth and threshold refinement. It never mutates the host's prompts, models, or behaviour. Improvement — and the optimisation it informs (Purpose 3) — is the host's responsibility, *enabled* by EvalGlass, not *performed* by it.

*Why.* Separation of concerns keeps the framework generic and keeps its incentives honest: a tool that both grades and edits the thing it grades cannot be trusted (P8). EvalGlass *informs* optimisation; it does not perform it.

*Implications.* No auto-tuning, no prompt rewriting, no model selection inside EvalGlass. The feedback loop produces *inputs to a decision* (failure profiles, regressions, drift), and a human or the host system decides what to change.

---

## 6. Resolving tensions — principle precedence

Principles will occasionally pull in opposite directions. When they do, resolve in this order:

1. **Trustworthiness over coverage** (P8). Never add a metric you cannot calibrate merely to be comprehensive. A smaller, honest scorecard wins — and no convenience, including a frictionless skill-driven setup, overrides this.
2. **Minimalism over completeness, for the core** (P3). When uncertain whether something belongs in the core, leave it out and make it a ring.
3. **Host autonomy over framework opinion** (P16, P1). EvalGlass surfaces; the host decides. Prefer the option that keeps control with the host.
4. **Genericity over convenience, for the spine** (P4) — but deliver convenience through optional defaults and adapters (P11). The core stays domain-agnostic; ergonomics live in the rings and the skill.
5. **Predictability over configurability** (P13). When a design could be more flexible but less conventional, prefer the conventional, so the skill's coding agent — and a human — can wire it in reliably.
6. **Eval validity over performance** (P8 over speed). Do not weaken an evaluation to make it fast; move it to async or offline instead (P12).
7. **A clean seam over a baked-in feature** (P3, P11). Prefer an extension point you can grow into over a feature welded into the core.

---

## 7. What these principles deliberately leave open

To honour "leave room for the architecture," the following are **not decided by this principles document** and are owned by the architecture / skill-design phase:

- Storage technology, schema, and retention model (the principle is only that there is a store behind an interface — P11).
- Implementation language(s) of the runtime (the vendoring delivery mechanism is settled — P2, P13).
- The skill's internal structure (SKILL.md layout, bundled scripts, reference files, templates) and the host-side convention it scaffolds (delivery *via a coding-agent skill* is settled — P13; its internals are a skill-design decision).
- The exact normalized dataset / trace / replay contracts and which subset of OpenTelemetry / OpenInference is adopted (P10 fixes route convergence and trace capability, not every field).
- Concrete signatures of the ports (trace source, dataset store, score sink, judge model, verifier, annotation store).
- The runner's internals: sync vs async, concurrency model, scheduling, retry policy.
- On-disk/in-store representation of datasets, traces, scores, scorecards, run records, baselines, and evidence packs.
- Judge-model provider abstraction and routing details.
- CI/CD and PR-gate integration specifics (P12 names PR review as the primary context; the mechanics are open).
- The form of any annotation surface (web, CLI, notebook) and whether it ships in v1.
- The exact grammar of the metric taxonomy (only that a hierarchical, host-extensible naming scheme exists, with each metric carrying a profile — P4, P12).
- Whether and how trajectory/step/session evaluation is realised (P5 names it as an expansion; the mechanism is open).

---

## 8. Non-goals

EvalGlass is explicitly **not**:

- A tracing or observability backend. It *consumes* traces and may *emit* scores to such a backend, but it does not replace one.
- A model or prompt optimiser / auto-tuner. It measures and informs optimisation; it does not change the host (P16).
- A general agent-orchestration framework.
- A fixed benchmark or a built-in metric set. Metrics are host-defined (P4).
- A second verdict engine hidden in the CLI, skill, report renderer, test system, or optional integrations.
- A fit for the most complex multi-agent systems out of the box (P5).
- A hosted SaaS or a standalone product the user logs into (P1).
- Primarily a published package (pip/npm) installed as a black-box dependency — the skill vendors editable, adaptable source into the host repo (P2).
- Dependent on any coding agent at runtime — the agent and its skill are integration-time only; once installed, the runtime runs on its own (P13).
- Dependent on synthetic data generation or an annotation UI in its core — both are expansion rings (P3, P15).
- A substitute for domain judgment — the host must still confirm what "correct" means; EvalGlass supplies the evaluation methodology, not the domain ground truth (P15).
- A guarantee of correctness or safety. It is an instrument; a passing scorecard is evidence, not proof (P8).

---

## 9. Glossary

- **Host project** — the agentic AI system that inherits EvalGlass and supplies the domain specifics.
- **Framework** — code that owns a lifecycle and calls host-supplied extension points (inversion of control), as opposed to a library (called by the host) or a system (a standalone deployment).
- **Runtime** — the vendored framework that runs in the host repo (in CI and beyond), independent of the skill or any coding agent.
- **Evaluation Core** — the effect-free runtime center that defines contracts, score semantics, aggregation, provenance, authority, baseline comparability, and the Verdict Engine.
- **Runtime Harness** — the effectful layer that loads config and data, calls ports/adapters, runs subprocesses or judge models, persists results, renders reports, and maps verdicts to CI behavior.
- **Verdict Engine** — the only component that converts scores, validity, authority, and baseline comparability into `pass`, `fail`, `blocked`, or `informational`.
- **EvalGlass skill** — the Claude Code / Codex skill that installs, integrates, and adapts EvalGlass in a host repo. It is the framework's delivery and integration vehicle, and it encapsulates the evaluation and AI-safety expertise the host need not have.
- **Coding agent** — an AI software-engineering agent (e.g., Claude Code, Codex) that runs the skill to perform the integration.
- **Vendoring / inheriting** — adopting EvalGlass by copying the runtime source into a host repo (done by the skill) and wiring it in, rather than calling a hosted service or installing a black-box package.
- **Domain judgment** — knowledge of what counts as a correct output in the host's domain; the one thing the host must supply (P15), distinct from evaluation / AI-safety expertise, which EvalGlass provides.
- **Trace** — the recorded execution of the host system (inputs, outputs, tool calls, steps, sub-agents), normalized to a common internal shape.
- **Unit of evaluation / granularity** — the slice of a trace a metric scores: a single LLM call (default), a step, a trajectory, or a session.
- **Evaluator** — a pure function `(example, context, evidence) → score(s)`.
- **Reference vs non-reference** — evaluation that compares to a gold standard vs evaluation using only the input and output.
- **Judge** — an LLM-as-judge evaluator; a non-reference, model-based metric.
- **Deterministic check** — a lightweight, rule-based, non-LLM evaluator (e.g., schema validity, field presence).
- **Gold / golden dataset** — input paired with a validated expected output (and/or expected trajectory); the reference for reference-based metrics.
- **Taxonomy / score config** — the hierarchical, host-extensible registry of metric names, each with a profile (`needs_gold`, `needs_llm`, latency, cost, data-policy, granularity).
- **Harness / execution mode** — how a run is executed: offline-batch (MVP, primarily in PR/CI), online-inline, online-async.
- **Port / adapter** — an abstract dependency interface (port) and a concrete backend implementation (adapter).
- **Scorecard** — the consolidated, authority-aware summary of a run, including metric summaries, diagnostics, provenance, baseline state, and Verdict Engine output.
- **RunRecord** — the complete machine-readable record of config, examples, metric specs, scores, diagnostics, provenance, authority, and verdict data for a run.
- **Authority** — typed evidence that a score, threshold, judge, dataset, policy state, or baseline may support a claim or gate.
- **Baseline comparability** — the typed claim that a previous run is comparable enough to support a regression assertion.
- **PR gate** — the use of the scorecard in continuous integration to block a pull request on regression (Purpose 2).
- **Provenance** — the configuration recorded with every score (what, against what, by which version, under which model/prompt).
- **Data policy** — the per-trace/dataset/metric attribute governing where data may travel and which model may see it; the generalised, soft form of an air gap.

---

## 10. Change log

| Date | Author | Change |
|---|---|---|
| 2026-05-22 | — | Initial design principles drafted (v1). |
| 2026-05-22 | — | v2: aligned with the canonical project description; added open-source identity and agent-mediated customisation; stated the three purposes; named PR review / CI as primary context; renumbered to 16 principles. |
| 2026-05-22 | — | v3: settled the delivery model — framework delivered as a Claude Code / Codex skill that installs and integrates the runtime by vendoring (P13 rewritten; P2 refit from package-install to skill-driven vendoring); stated the division of expertise (host supplies domain judgment; framework and skill carry evaluation and AI-safety expertise — North Star, P8, P15); §7/§8/§9 updated accordingly. |
| 2026-05-27 | — | v4: aligned with the architecture contracts: effect-free Evaluation Core, effectful Runtime Harness, one Verdict Engine, typed Scorecard / RunRecord JSON, typed authority, baseline comparability, route convergence, and host-owned truth artifacts. |
