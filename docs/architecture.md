# EvalGlass Implementation Architecture

**Status:** product implementation architecture (current — aligned with the shipped framework, milestones M0–M7, the R-tranche live connectors, and the ADR record in `../adrs/`)  
**Date:** 2026-07-22 (revised; first issued 2026-05-27)  
**Scope:** EvalGlass only  
**Excludes:** test system, execution loop, validator gate, scan gate, and implementation-gate architecture

This document defines the streamlined implementation architecture for EvalGlass
itself. EvalGlass should stay small enough to adopt, but not so small that it
becomes a toy score runner. The implementation keeps the real evaluation
capabilities: reference and non-reference metrics, trace-native input, typed
evidence, judge-assisted metrics, provenance, baseline comparability, authority,
and one Verdict Engine.

The streamlining target is implementation complexity, not evaluation capability.

## Contents

1. [Scope And Principle](#1-scope-and-principle)
2. [Product Rings](#2-product-rings)
3. [Runtime Flow](#3-runtime-flow)
4. [Trace And Integration Model](#4-trace-and-integration-model)
5. [Evaluation Core](#5-evaluation-core)
6. [Authority And Verdict](#6-authority-and-verdict)
7. [Runtime Harness](#7-runtime-harness)
8. [EvalGlass Plugin](#8-evalglass-plugin)
9. [Artifacts And Host Truth](#9-artifacts-and-host-truth)
10. [Repository Layout](#10-repository-layout)
11. [Implementation Slices](#11-implementation-slices)
12. [Acceptance](#12-acceptance)

## 1. Scope And Principle

EvalGlass is a vendored, local-first evaluation framework for LLM applications.
It measures host behavior from supplied evidence and reports what can honestly
be claimed. It does not improve the host application, approve domain truth, or
become a hosted platform.

**Positioning — Core executes.** Core is the open, host-directed evaluation
runtime: you tell it what to evaluate and it executes honestly, giving a rigorous
system to *define, run, compare, and retain* evaluations. It never inspects an
application to decide, on its own, what should be tested. Deriving *what* to
measure from an application (metric discovery) is deliberately **out of scope**:
EvalGlass runs the checks the host authors and derives none on its own. This
document specifies Core only.

**Primary rule:** a green or non-failing EvalGlass result must never imply more
evidence, authority, calibration, comparability, or validity than the run
actually has.

In scope:

- Vendored runtime under `evals/_evalglass/`.
- Effect-free Evaluation Core and Verdict Engine.
- Runtime Harness with local datasets, local traces, subprocess replay, reports,
  baselines, and CI exits.
- Narrow trace integration model that can support OpenTelemetry /
  OpenInference-shaped traces and backend adapters.
- Integration-time plugin that vendors and scaffolds safely.

Out of scope:

- EvalGlass Testing System architecture and proof strategy.
- Execution-loop orchestration and independent implementation gates.
- Detailed Jira backlog mechanics.
- Hosted dashboards, broad provider abstractions, annotation apps, synthetic
  data systems, and release hardening.

Design posture:

- Trustworthiness over coverage.
- Minimal implementation over platform breadth.
- Host-owned truth over framework opinion.
- Trace-native contracts over vendor-specific trace assumptions.
- Typed JSON artifacts over report prose.

**Streamlining rule:** reduce concrete integrations, workflow breadth, and module
sprawl. Do not reduce the evaluation meaning model, trace contracts, metric
registry, authority model, or evidence discipline.

## 2. Product Rings

The streamlined product is organized as rings. Rings are not separate products;
they are implementation boundaries that keep EvalGlass useful without turning it
into a platform. The inner rings are required. Outer rings attach through ports
and can grow after the first honest instrument works.

| Ring | Owns |
|---|---|
| Evaluation Spine | Core contracts, evaluator protocol, metric registry, score states, diagnostics, aggregation, authority, Verdict Engine, local dataset route, local trace route, Scorecard, and RunRecord. |
| Trust Layer | Provenance, baseline comparability, threshold approval, data policy, judge calibration, and clear blocked/informational states. This is not optional polish; it prevents false confidence. |
| Integration Layer | `TraceSource`, `JudgeModel`, `TaskRunner`, `ResultStore`, and `ScoreSink` ports. Ship one narrow local adapter first, then add trace backend and provider adapters through the same contracts. |
| Adoption Layer | Plugin vendoring, manifest, lock file, scaffolded host-owned truth, first-run guide, and conservative re-vendoring. Discovery should be useful, not magical. |

The product still has three EvalGlass-owned areas plus host-owned truth. The
split is architectural, not cosmetic: it decides what code may make meaning,
what code may perform effects, and what code may grant authority.

| Area | Owns | Must not own |
|---|---|---|
| Evaluation Core | Meaning, public contracts, score states, validity, aggregation, provenance, authority, baseline comparability, Verdict Engine. | File I/O, network I/O, subprocesses, clocks, randomness, config loading, reports, provider SDKs, CI shell behavior. |
| Runtime Harness | CLI, config loading, the plan-before-effects preflight (`EvaluationPlan`, ADR 0050) that drives replay/judge collection and `preflight`/`--dry-run`, the connected-evidence contracts (local `connect --from` import, per-source coverage manifests, behavior-layer preservation + bounded hydration, the `assemble` evidence pipeline, and the proposed-reference lifecycle — ADR 0051), adapters, ports, replay, judge evidence collection, result persistence, report rendering, exit mapping. | New score meanings, duplicate verdict logic, hidden authority, silent host approval. |
| EvalGlass Plugin | Repo discovery, install plan, vendoring, manifest, lock file, scaffold, CI snippets, confirmation checklist, re-vendoring. | Runtime execution, metric authority, domain approval, automatic gating, hidden host mutation. |
| Host-Owned Truth | Examples, references, rubrics, thresholds, calibration, baselines, evaluator code, domain approvals. | Managed framework internals. |

## 3. Runtime Flow

All input routes converge before scoring. Dataset examples, recorded traces,
tracing-platform imports, and subprocess replay all become the same
evaluator-visible contracts. Reports and CI behavior are emitted only after the
core returns typed run data and verdict payload.

```text
Load
  config, datasets, traces, baselines, policy, rubrics, calibration,
  thresholds, and host evaluators
Collect
  recorded behavior or subprocess JSON in/out
Prepare
  TraceEnvelope -> EvalUnit -> Example + EvidenceBundle
Score
  registry validation, prerequisites, effect-free evaluators, normalization
Resolve
  aggregation, provenance, baseline comparability, authority
Decide
  Verdict Engine emits pass, fail, blocked, or informational
Emit
  RunRecord, Scorecard, Markdown, CI annotations, baseline by explicit command,
  and exit code
```

Failure taxonomy matters. Setup errors, task failures, missing evidence, blocked
metrics, invalid measurements, low scores, and infrastructure errors are
different states. None may be collapsed into an ordinary low score.

## 4. Trace And Integration Model

Trace support is a first-class product capability, not a late add-on. The
simplification is that EvalGlass standardizes one trace boundary and avoids
baking any tracing vendor into the core.

Local trace JSONL proves the route first. OpenTelemetry / OpenInference-shaped
conformance and backend adapters attach through `TraceSource`.

```text
Dataset JSONL
  examples, references, dataset status, dataset version

Trace Sources
  local trace JSONL first
  OpenTelemetry / OpenInference-shaped traces next
  platform adapters later

TraceEnvelope
  vendor-neutral behavior, metadata, timing, model/tool details where supplied,
  data policy, provenance

EvalUnit + Example
  call-level default
  step, trajectory, and session units supported additively (ADR 0020:
  EvalUnit.members) without changing evaluator meaning
```

| Integration capability | Keep in architecture | Streamline for first build |
|---|---|---|
| Trace import | `TraceSource`, `TraceEnvelope`, `EvalUnit`, trace provenance, data policy, malformed trace diagnostics. | Implement local trace JSONL and one open-convention conformance shape before platform SDKs. |
| Trace backend adapters | Adapter contract and mapping rules from external spans/messages/tool calls to `TraceEnvelope`. | Local JSONL and the open-convention shape prove the route first. Three real **live connectors** now ship behind one shared `BaseTraceConnector` boundary (ADR 0033) — **Langfuse** (0034), **Phoenix** (0035), and **LangSmith** (0036) — each pinning exactly one provider SDK in its own extra, imported lazily inside the lane only. Opt-in, deletable, and `live_lane`-only; the required, hermetic tier imports no provider SDK. No broad adapter marketplace. |
| Score sinks | `ScoreSink` consumes immutable Scorecard data for Markdown, CI, HTML, or optional backend publication. | Ship local JSON/Markdown/terminal/CI first. A dashboard-style **HTML report** (`report.html`, ADR 0043) renders the same typed Scorecard — self-contained, no network, never recomputes the verdict. Backend upload comes later and never mutates verdict or authority. |
| Judge providers | `JudgeModel` evidence contract, rubric provenance, parser diagnostics, calibration state. | Fake judge evidence first (required tier). Real judges are config-selectable on the same evidence route: a **host command judge** (a subprocess `JudgeModel`, ADR 0042) and a first-class **`openai_compatible`** judge (an OpenAI-compatible chat endpoint with host-injected rubrics, ADR 0040/0052) — the credential is an env-var name resolved at effect time, the adapter is imported lazily, and the required tier ships no provider SDK. The `live-judge` lane (a host judge endpoint, ADR 0016) remains behind the same port. All stdlib-transport, opt-in, deletable, and uncalibrated → informational. Still no broad provider abstraction. |

**Trace rule:** tracing platforms may supply behavior and receive scores, but
the Evaluation Core sees only EvalGlass contracts. Vendor SDKs stay in adapters
or optional integration modules.

## 5. Evaluation Core

The core is the product's meaning layer. It is deterministic, effect-free, and
vendor-neutral. Streamlining the core means fewer implementation files and
sharper boundaries, not fewer concepts. Trace contracts, evidence, score
validity, authority, and verdicts remain first-class.

Recommended first package shape:

```text
evals/_evalglass/core/
  __init__.py
  contracts.py
  scores.py
  diagnostics.py
  registry.py
  evaluators.py
  aggregation.py
  statistics.py       # honest interval estimators: Wilson, Student-t, rule-of-three (M7)
  estimate.py         # Estimate = point + confidence interval, method chosen by metric meaning (M7)
  claim_spec.py       # optional construct/validity record per metric (M7)
  provenance.py
  authority.py
  grant.py            # digest-bound, capability-typed AuthorityGrant (M7)
  agreement.py        # computed JudgeAgreementStudy (calibration is measured, not declared) (M7)
  comparison.py       # paired baseline comparison over shared items (M7)
  judge_instrument.py # judge instrument identity (M7)
  decision.py         # DecisionPolicy + pure apply_policy: estimate is not decision (M7)
  verdict.py
  engine.py
  builtins/
    exact_match.py
    set_overlap.py
    field_presence.py
    structural_shape.py
    judge_score.py
    trajectory_shape.py
```

These files may split later if real complexity demands it. The first
implementation should keep related score, metric, prerequisite, and
normalization concepts close enough to review.

Core exclusions:

- No filesystem, network, subprocess, environment, clock, or randomness access.
- No config loading, report rendering, CLI framework, or CI shell behavior.
- No provider SDKs, tracing backends, eval frameworks, workflow engines, or
  optional integration packages.
- No hidden global state that changes the same input into different output.

Core responsibilities:

| Responsibility | Meaning |
|---|---|
| Contracts | `TraceEnvelope`, `EvalUnit`, `Example`, `EvidenceBundle`, `JudgeEvidence`, `MetricSpec`, `Score`, `ScoreBatch`, `RunRecord`, `Scorecard`, and authority/verdict payloads are JSON-compatible public data. |
| Registry | Metric names, versions, score types, ranges, direction, evidence needs, aggregation, prerequisites, evaluator refs, and authority declarations are validated before measurement. |
| Evaluators | Evaluators receive `Example`, context, and evidence. They return scores or measurement states, never verdicts. Built-ins stay deterministic and domain-neutral. |
| Normalization | Raw evaluator returns are checked for declared metric name, type, range, status, diagnostics, evidence refs, evaluator version, and provenance. Invalid returns become structured errors. |
| Aggregation | Only `scored` plus `valid` measurements enter numeric math. Aggregates preserve excluded status counts, representative diagnostics, threshold state, and direction. |
| Estimate (M7) | On top of the point value, each metric carries an `Estimate`: the same point plus an honest confidence interval whose method is chosen from the metric's declared meaning — Wilson for a proportion, Student-t for a continuous mean, rule-of-three for an all-same outcome, and an explicit "no interval for this aggregation" diagnostic for order statistics. Interval bounds are rounded to a platform-independent precision (ADR 0044) so artifacts stay reproducible and comparable. An optional `ClaimSpec` records the construct/validity argument for the metric. |
| Provenance | Every score and run carries structured fingerprints for framework version, metric spec, evaluator version, dataset/reference, examples, evidence, runtime config, policy, authority, and baseline dimensions. Scores also carry optional subject identity (`example_id` / `unit_id`, ADR 0024) as additive provenance for honest per-call grouping. |

Score states:

| Score status | Meaning | Aggregation rule |
|---|---|---|
| `scored` | A metric produced a meaningful value. | Included only when measurement validity is `valid`. |
| `blocked` | Required evidence, capability, policy, prerequisite, or comparability is missing. | Excluded from math; blocks active gates. |
| `non_evaluable` | The example or unit cannot meaningfully support the metric. | Excluded from math; blocks only when required. |
| `skipped` | The metric was intentionally not run by config, profile, or applicability rule. | Excluded from math; may block if the metric was required. |
| `error` | Evaluator or evidence parser failed unexpectedly. | Excluded from math; blocks active gates. |

## 6. Authority And Verdict

EvalGlass separates measurement from authority. A score can be useful and still
informational. A run can be blocked because the system refuses to make an
unsupported quality claim.

**Estimate is not decision (M7).** A point value is not the quantity a gate
compares to a threshold. When a metric declares an optional `DecisionPolicy`, the
Verdict Engine decides over the metric's `Estimate` through the pure
`apply_policy`: it gates on the **lower confidence bound** (not the point) and on
declared **adequacy** — `min_n_effective` and a maximum tolerated missing
fraction — so a one-item gate, a wide-interval gate, or a thin-coverage gate
**blocks** rather than passing on a lucky point. A metric with no decision policy
keeps the legacy point-vs-approved-threshold path unchanged; the decision policy
is opt-in and additive.

**Capability-typed, digest-bound authority (M7).** Authority is granted, not
assumed. An `AuthorityGrant` is typed by the *capability* it confers and is
**digest-bound**: it authorizes a specific artifact (dataset, threshold,
calibration) only when the artifact's digest matches the grant, so a stale or
swapped artifact cannot inherit an old approval. Judge calibration is a
**computed** `JudgeAgreementStudy` (agreement is measured against host labels,
not declared in a file), which means the built-in *fake* judge can never earn
gating authority — its instrument identity carries no calibration capability.

Authority inputs:

- Dataset: `proposed`, `validated`, `retired`.
- Metric: `draft`, `informational`, `calibrating`, `gating`, `retired`.
- Threshold: `proposed` or `approved`.
- Judge: `uncalibrated`, `calibrating`, `calibrated`, `drifted`, `retired`.
- Data policy and baseline comparability state.

Resolved authority should include:

- `can_gate`.
- `authority_level`: `none`, `informational`, or `gating`.
- Typed reason codes and required actions.
- Changed baseline dimensions when regression claims are not comparable.

Verdict payload should include:

- Verdict value and `ci_should_fail`.
- Active gates, failing gates, blocked gates, informational metrics.
- Authority explanation and diagnostics.
- Machine data used by reports and CI.

| Condition | Verdict | CI meaning |
|---|---|---|
| No metric has resolved gating authority. | `informational` | Exit zero. State that no active gate existed. |
| All active gates are valid, comparable where required, and above approved thresholds. | `pass` | Exit zero. |
| An active gate is validly measured and fails an approved threshold. | `fail` | Exit non-zero with metric, threshold, value, and diagnostic cause. |
| An active gate is blocked, errored, non-evaluable, policy-forbidden, skipped when required, or missing required comparable baseline. | `blocked` | Exit non-zero because EvalGlass cannot make an honest quality claim. |

Implementation rule: CLI code, reports, adapters, sinks, plugin code, and host
tests may consume the verdict payload. They must not reimplement verdict or
authority rules.

## 7. Runtime Harness

The Runtime Harness owns all effects. It turns host files, traces, replayed
outputs, and collected evidence into core inputs, then turns core outputs into
persisted artifacts and process behavior.

The streamlined rule is one clear port model with narrow first adapters, not a
large integration framework.

| Port | Purpose | MVP adapter | Forbidden behavior |
|---|---|---|---|
| `DatasetStore` | Reads examples, references, dataset status, and dataset version. | Local JSONL in `evals/datasets/`. | Silently treating proposed data as validated. |
| `TraceSource` | Yields recorded host behavior. | Local JSONL in `evals/traces/`; open-convention trace shape next. | Passing vendor trace shape to evaluators. |
| `TaskRunner` | Runs the host system when fresh outputs are needed. | Subprocess JSON in/out. | Mutating host state without an explicit host command contract. |
| `JudgeModel` | Collects judge evidence only when a metric declares that need. | Fake judge evidence for required local flows; minimal live adapter later. | Returning verdicts or setting authority. |
| `ResultStore` | Persists run records, scorecards, baselines, provenance, and reports. | Filesystem JSON and JSONL. | Promoting baselines during ordinary evaluation. |
| `ScoreSink` | Presents typed results to humans and systems. | JSON, Markdown, terminal summary, dashboard HTML report (ADR 0043), CI annotations, exit code. | Inventing authority or mutating Scorecard data. |

Runtime rules:

- Harness validates config into typed runtime configuration before calling core.
- YAML may be used with safe loading.
- Config defaults must not grant authority.
- Dataset, trace, and subprocess replay routes all become `Example` plus
  evidence before evaluator execution.
- Raw traces and adapter objects never reach evaluators.
- Harness failures before a core verdict use a separate infrastructure error
  path. They must not be reported as host quality failures.

Adapter policy:

- Keep port contracts stable.
- Ship few concrete adapters first.
- Local dataset, local trace, filesystem result store, and subprocess replay are
  required.
- Trace backend, score sink, and live judge adapters are added only after the
  local route proves the contract.

**Optional lanes attach through a visible seam (ADR 0031).** Live connectors,
provider judge lanes, and hosted sinks are opt-in `ExtensionLane`s declared in a
`lanes:` config block. The runner attaches them at a single runner-attach seam;
their outcomes ride a `RunRecord.lane_results` side channel that never feeds the
verdict. A missing extra makes a lane skip cleanly; deleting a lane leaves the
required tier byte-identical. No required import path loads a lane, and lane
evidence can inform diagnostics but never grants authority.

## 8. EvalGlass Plugin

The EvalGlass Plugin is the integration-time adoption layer. It is how a host
adopts EvalGlass, but it is not part of runtime execution and cannot grant
metric authority.

The plugin is a **Claude Code plugin** — with Codex as a second runtime (ADR
0022 / 0023) — whose model-invoked skills drive a deterministic engine, the
`evalglass.installer` package: fail-closed subcommands `discover | plan |
install | revendor`, invoked as `python -m evalglass.installer` or the
`evalglass-install` console script (ADR 0010; the package was named `skill`
before ADR 0026, which also re-homed the agent recipe into the plugin).

**Delivery boundary.** The plugin is *delivery and packaging only*: it freezes
the effect-free core, the single Verdict Engine, and the vendoring boundary,
adds zero core imports, introduces no second verdict path, and is **never
vendored** into a host — removing it leaves every host verdict byte-identical.
The direct `python -m evalglass.installer install --root .` path is unchanged.

The plugin should be boring by design: vendor, scaffold, explain, and preserve
host work before it attempts smart repo surgery.

Plugin flow:

1. **Discover** repo shape, likely LLM call sites, existing traces or logs,
   language conventions, ignore files, and CI conventions conservatively.
2. **Plan** managed files, host-owned files, trace route choices, command
   snippets, and validation work required from humans.
3. **Vendor** managed runtime files under `evals/_evalglass/`, write
   `vendor-manifest.json`, and write `evalglass.lock`.
4. **Scaffold** host-owned config, datasets, local trace samples, rubrics,
   evaluators, calibration placeholders, baselines, reports folder, and smoke
   tests.
5. **Confirm** the first informational path and ask for human validation before
   any scaffolded data, threshold, or rubric can gate.
6. **Re-vendor** with dry-run upgrades, managed-file replacement only,
   host-owned preservation, host patch detection, and conflict reporting.

Plugin boundary: generated gold, proposed thresholds, placeholder rubrics, and
agent edits are informational until host validation, calibration, approval, and
comparable baselines exist.

**Authoring metrics (host-directed).** EvalGlass is the framework, not the
oracle: it supplies the metric vocabulary, the built-in evaluators, and the
host-evaluator seam, and lets the **host** decide *what* to measure. The
`authoring-a-metric` skill turns a check the host names — a failure to catch, a
contract to enforce, an output rule — into a `MetricSpec` in
`evals/evalglass.yaml` across three tiers (runtime / reference / judge). Two
honesty invariants hold: (1) every scaffolded asset lands **`proposed` /
`uncalibrated`** — informational until the host validates, approves a threshold,
and (for judges) calibrates; and (2) the framework **derives no metrics on its
own** — automated metric discovery is deliberately out of scope for the core;
EvalGlass runs the checks the host authors and infers no metrics itself. The host
decides; the agent scaffolds; the host validates.

## 9. Artifacts And Host Truth

Machine-readable artifacts are the product surface. Markdown and terminal
summaries exist for readability, but they are always renderings of typed data.

Primary machine artifacts:

- `RunRecord`: complete persisted record of config, examples, metric specs,
  scores, evidence refs, diagnostics, provenance, authority, baseline state, and
  verdict.
- `Scorecard`: compact machine and human summary with metric summaries, status
  counts, per-metric `Estimate`s (point + confidence interval), diagnostics,
  authority explanation, baseline state, and Verdict Engine output.
- `ComparableRunFingerprint`: structured dimensions proving whether current and
  baseline runs can support regression claims; when comparable, a **paired
  comparison over shared items** (M7) yields the honest delta instead of a bare
  point difference.

Host-owned truth:

- Datasets and references.
- Rubrics, judge calibration, and threshold approval records.
- Baselines and comparable run records.
- Host evaluators and domain-specific correctness logic.
- Human validation and approval metadata.

| Output | Authority | Rule |
|---|---|---|
| `scorecard.json` | Primary summary contract. | Reports and CI annotations must match it. |
| `runrecord.json` | Complete audit record. | Must retain diagnostics, provenance, evidence refs, and verdict payload. |
| `report.md` | Human-readable rendering. | Cannot contain authority or verdict logic absent from typed data. |
| `report.html` | Dashboard-style rendering (ADR 0043). | Self-contained (no network); renders the same verdict/authority/estimates as the Scorecard and recomputes nothing. |
| `baseline.json` | Host-owned comparison record. | Updated only by explicit promote/update command. |
| `vendor-manifest.json` | Managed file boundary. | Records source version, paths, checksums, purpose, and host patch state. |
| `evalglass.lock` | Installed runtime identity. | Records framework version, installer/source metadata, installed features, and optional extras. |

## 10. Repository Layout

The installed host layout makes the managed framework replaceable and the
host-owned truth reviewable. The framework repository may use a different source
layout, but the vendored host boundary must stay clear.

Installed host repo:

```text
<host-repo>/evals/
  _evalglass/
    core/
    harness/
    adapters/
    vendor-manifest.json
  evalglass.lock
  evalglass.yaml
  datasets/*.jsonl
  traces/*.jsonl
  evaluators/*.py
  rubrics/*.md
  calibration/*.json
  baselines/*.json
  reports/
  tests/
```

Framework repo shape:

```text
<evalglass-framework-repo>/
  src/evalglass/
    core/
    harness/
    adapters/
    installer/
  tests/
    core/
    runtime/
    installer/
    integration/
  examples/
  docs/
```

Managed file rule: re-vendoring may replace files under `_evalglass/`. It must
not clobber datasets, traces, evaluators, rubrics, calibration records,
baselines, reports, or host tests.

## 11. Implementation Slices

Build order protects the product from false confidence while keeping trace
capability central. The core and local runtime prove the contracts first. Trace
backend adapters and live providers come after the local instrument is
trustworthy, but their contracts are designed from the beginning. All milestones
below (M0–M7) are now implemented; this table records the build order and
intent. The dated, scoped record of what shipped lives in `../CHANGELOG.md`, and
the per-decision record in `../adrs/`.

| Milestone | Focus | Exit criterion |
|---|---|---|
| M0 - Evaluation Core | Core contracts, trace-aware units, evidence model, score model, diagnostics, registry, evaluator protocol, aggregation, provenance, authority, verdict matrix, serialization. | Core scores fixture examples and trace-shaped examples, then returns honest `RunRecord` and `Scorecard` data without runtime adapters. |
| M1 - Local Runtime Harness | CLI, config boundary, JSONL datasets, local trace JSONL, route convergence, deterministic evaluator loading, local reports, result persistence. | A host repo can run dataset and trace evals locally with clear diagnostics and authority explanation. |
| M2 - Replay, Baselines, CI | Subprocess task runner, baseline fingerprints, comparable-run checks, policy routing, CI annotations, exit codes. | CI can pass, fail, block, or report informational solely from core verdict data. |
| M3 - EvalGlass Plugin | Repo discovery, vendoring, manifest, lock file, host scaffold, local dataset/trace examples, safe defaults, first-run checklist, re-vendoring. | A new host repo can be integrated with managed files separated from host truth and runtime independent after install. |
| M4 - Judges And Calibration | JudgeModel port, fake judge, rubric versioning, judge evidence, calibration records, threshold approval records, minimal live-provider lane after fake evidence proves the contract. | Judge metrics can gate only with calibration evidence and approved thresholds; live providers remain isolated from required paths. |
| M5 - Optional Extensions | An `ExtensionLane` framework (opt-in, isolated, deletable) plus trace backend adapters, hosted score sinks, richer trajectory/session units, async observation, and generated-evidence governance for synthetic / annotation / benchmark inputs as separate rings (ADR 0017–0021). | Every extension attaches through ports, preserves EvalGlass contracts, and can be removed without altering core meaning. |
| M6 - Live Trace Connectors (R-tranche) | Real trace-import connectors behind one shared `BaseTraceConnector` boundary and an optional-provider-SDK policy — Langfuse, Phoenix, LangSmith — each pinning one SDK in its own extra, imported lazily, `live_lane`-only; plus the deliberate never-build of a per-source-function score view (ADR 0033–0037). | Each connector normalizes to `TraceEnvelope` with no vendor object leaking; the required, hermetic tier imports no provider SDK and stays green when every connector is deleted. |
| M7 - Epistemic Core | Wilson/Student-t `Estimate`s, a `DecisionPolicy` that gates on the confidence bound and adequacy, capability-typed digest-bound `AuthorityGrant`s, computed `JudgeAgreementStudy` calibration, paired baseline comparison, and `ClaimSpec` — plus the OpenAI-compatible and host-command judge lanes (0040/0042) and the HTML Scorecard report (0043); interval bounds rounded for portability (0044). | Gates decide on honest intervals, not lucky points; a fake or uncalibrated judge can never gate; every scaffolded asset stays non-authoritative until the host validates. |

**Post-M7 robustness increments.** A run of additive slices layered on the M0–M7
spine without changing its meaning: aggregate `EvalUnit`s where a member's egress
is the worst of its parts (ADR 0045); the `connect --live` config scaffolder that
wires an opt-in trace-connector lane and imports no SDK (ADR 0046); diagnostic
**clusters** that group a metric's failing items by their diagnostic `code`,
recomputed from the saved scores on load so a hand-edited cluster fails closed
(ADR 0047); and the scheduled **drift watcher** (`watch`) — one run compared to a
baseline, written to `drift.json`, that flags a `regression` only when the runs
are comparable and never changes an exit code or promotes a baseline (ADR 0048).

**Metric-scoped scoring, authority, and comparison.** A further additive tranche
makes mixed-source runs precise without weakening any invariant: a metric may
declare explicit **source bindings** (`sources: [{name, role}]`) so its executed
population is only the evidence its construct consumes, not the union of every
configured source (ADR 0056); **authority resolves per metric over that consumed
set**, so an unrelated proposed/forbidden source cannot dilute a bound metric and
a selector cannot launder an unsafe one, while an unbound metric keeps the
conservative run-global worst (ADR 0057); each metric persists a typed
**`PopulationSummary`** reconciling its plan-derived coverage with its
score-derived terminal states, so a metric that scored 1 of 100 eligible subjects
can no longer read as fully covered (ADR 0058); and the item-paired baseline
comparison becomes a typed **`ComparisonResult`** on the primary artifact — a
numeric, direction-adjusted delta only when `comparable`, changed fingerprint
dimensions otherwise — shared by both `run` and `watch` and carrying no verdict or
exit (ADR 0059). All four are byte-identical for a config that does not use them.

**Diagnostic scorecard and honest progression.** The default `report.html` is now a
diagnostic-first **dashboard over all scores** (no per-score report), rendered from a
typed, score-neutral projection **`evalglass.dashboard/1`** (`dashboard.json`) that
*copies* verdict, per-metric authority, gate state, population, estimate, and typed
comparison from the primary artifacts and computes none of them — no Verdict Engine or
authority resolver import, no aggregate subtraction, non-scored rendered as absence,
informational never styled as pass (ADR 0060). Host-owned **display metadata**
(`metrics[].display`, `dashboard:`) supplies label/workflow/tier/description/attention
with deterministic neutral fallbacks (tier derives from the typed lens/evaluator, never
a name/reason heuristic) and grants no authority; a host-declared versioned `composite`
is the only licensed overall mean. The self-contained template assets are vendored into
a host so the report renders after the plugin is removed; the previous renderer stays
opt-in for one release. A run is also captured **immutably**: alongside the addressable
`reports/<run-id>/` latest alias, each distinct run is snapshotted under
`reports/.series/runs/<run_key>/` with integrity coverage and recorded in an append-only,
repairable index that the dashboard reads for **descriptive** coverage history only —
never a regression claim, which stays the typed comparison (ADR 0061). A `series` verb
inspects and repairs the index; it promotes no baseline and changes no verdict. Every
new field emits only when present, so the primary JSON and the goldens are byte-identical.

## 12. Acceptance

| Area | Acceptance |
|---|---|
| Core | Effect-free, vendor-neutral, deterministic, JSON-compatible, and tested for score status, validity, diagnostics, aggregation, provenance, authority, baseline comparability, and verdicts. |
| Runtime | Runs local datasets, local traces, fake judge evidence, subprocess replay, reports, baselines, and CI exits without owning evaluation meaning. |
| Plugin | Vendors managed files, scaffolds host-owned assets with informational defaults, records manifest and lock data, and stops for human validation before authority exists. |
| Trust | No Scorecard can imply authority unsupported by dataset state, metric state, approved threshold, judge calibration, data policy, provenance, or baseline comparability. |
| Integration | Trace and score integrations use ports and normalized contracts. Vendor-specific behavior never reaches evaluators or the Evaluation Core. |

Final question:

```text
Could a green Scorecard be misread as proof of correctness when the run is
informational, unvalidated, uncalibrated, non-comparable, non-evaluable, or
partly blocked?
```

If yes, the implementation architecture is not complete.
