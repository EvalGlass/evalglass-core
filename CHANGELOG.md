# Changelog

All notable changes to EvalGlass are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0, the public API and
plugin surface may still change.

## [Unreleased]

### Changed

- **Plugin-facing docs align with the shipped capability (no false confidence, applied to our own
  storefront).** Removed every reference that implied an "advanced discovery engine" — the
  `Core executes · Discovery finds · Intelligence explains` three-tier framing and the pointers to a
  separate (private, unreachable) `evalglass-discovery` repo — from the README, architecture doc,
  `AGENTS.md`, the plugin/marketplace descriptions, and the ADR index. What `evalglass-core` actually
  ships is a single, conservative, read-only **candidate call-site inventory** (`installer discover`);
  automated *metric discovery* (deriving what to measure from an app's traces, prompts, and schemas)
  is deliberately **out of scope** — EvalGlass runs the checks the host authors and derives none on
  its own. No runtime, public-contract, authority, or verdict-behaviour change.

## [0.2.1] - 2026-08-20 (pre-alpha)

Public-launch preparation — the final pre-public cut. No runtime, public-contract, authority, or
verdict-behaviour change: the vendored runtime and all typed artifacts are behaviourally identical to
`0.2.0`.

### Added

- **CodeQL static analysis (SAST).** A visibility-gated `codeql.yml` closes the one gap in the
  security tier (TruffleHog, Trivy, pip-audit, and licensecheck are not SAST): while the repository
  is private the analysis job is skipped and the workflow stays green; it activates automatically the
  moment the repository is made public.
- **Contributor Covenant 2.1 Code of Conduct** — standard community-health hygiene for a public
  project.

### Removed

- **The internal `docs/plugin/` folder.** It held development and QA process material — the
  per-milestone acceptance runbooks, an implementation-lessons log, marketplace-submission notes, and
  the plugin release checklist — none of it external documentation. The release gates it described are
  enforced by the `tests/plugin/` suite and summarised in `CONTRIBUTING.md`.

### Fixed

- Scrubbed a local absolute path and internal tool versions from the docs; corrected broken links (a
  non-existent architecture build-contract link, a stale ADR link, and the clone-directory snippet)
  and replaced a reference to a separate private repository with the public docs site.

### Security

- Enabled repository secret scanning with push protection and Dependabot alerts / security updates.

## [0.2.0] - 2026-08-20 (pre-alpha)

Refines the packaging and the product positioning on top of the complete `0.1.0` core; the runtime,
public contracts, authority, and verdict behaviour are unchanged.

### Added

- **Modular optional-dependency extras — lean by default, complete by composition.** Grouped extras
  compose the granular connector extras via self-reference: `evalglass[traces]` installs all three
  trace connectors (Langfuse + Phoenix + LangSmith), and `evalglass[all]` the full optional surface;
  `openai` and `hosted` are stdlib-only markers (the OpenAI-compatible judge and the hosted/async
  sinks use stdlib `urllib`, so there is no SDK to install). Because the grouped extras are pure
  self-references they pin **no** provider SDK directly — `project.dependencies` stays PyYAML-only,
  the required import closure stays SDK-free, and the strict dependency-budget guard is unchanged.

### Changed

- **Canonical Core positioning.** The README and the architecture docs now state the product
  boundary explicitly — **Core executes** — and frame Core as the open, host-directed evaluation
  runtime that gives your team a rigorous system to *define, run, compare, and retain* evaluations
  over checks you own. It never inspects an application to decide, on its own, what to test; deriving
  *what* to measure (metric discovery) is deliberately out of scope for the core.

### Notes

- No runtime, public-contract, authority, or verdict-behaviour changes since `0.1.0`. The vendored
  runtime and all typed artifacts are behaviourally identical; only the version-bearing surfaces,
  the reproducibility fingerprints in the committed goldens (which fold in `__version__`), and the
  docs move to `0.2.0`.

## [0.1.0] - 2026-08-20 (pre-alpha)

Initial public release of **EvalGlass core** — the pure evaluation framework. EvalGlass is a small,
vendored, local-first evaluation framework for LLM applications, delivered as a Claude Code / Codex
plugin over an effect-free Evaluation Core with a single Verdict Engine. Its governing rule is **no
false confidence**: a green or non-failing result never implies more evidence, authority,
comparability, calibration, or safety than the run actually has. A fresh run is **informational** by
design — real, non-reference signal, but not a quality pass; gating requires host-validated gold, an
approved threshold, and (for judges) calibration.

EvalGlass is the **framework, not the oracle**: it supplies the machinery and lets *you* decide what
to measure. You know your app and how it fails; tell the agent the check you want and the
`authoring-a-metric` skill scaffolds it. Automated *metric discovery* — deriving what to measure from
an app's traces, prompts, and schemas — is deliberately **out of scope** for the core; EvalGlass runs
the checks you author and derives none on its own.

### Added

#### Evaluation Core (effect-free, standard-library-only)

- **Typed contracts and score semantics.** `TraceEnvelope -> EvalUnit -> Example`, `MetricSpec`,
  `Score`/`ScoreBatch`, `RunRecord`, and `Scorecard` are typed, JSON-round-trippable dataclasses.
  Status (`scored`/`blocked`/`non_evaluable`/`skipped`/`error`) and validity
  (`valid`/`invalid`/`not_measured`/`not_applicable`) are explicit; a blocked, skipped, errored, or
  non-evaluable state is never encoded as `0.0`, and every non-perfect state carries structured
  diagnostics (code, severity, message, location, cause, evidence refs).
- **Single Verdict Engine.** Only the Verdict Engine turns score and authority state into a run
  outcome — no active gates → `informational`; an active gate blocked or missing required evidence →
  `blocked`; validly measured below an approved threshold → `fail`; all active gates valid,
  comparable where required, and passing → `pass`. Every outcome carries `ci_should_fail`; nothing
  else in the system may compute a verdict.
- **Typed authority.** Dataset status, metric status, threshold approval, judge calibration, and
  data-policy state are explicit inputs to authority resolution — authority is data, never report
  prose. Scaffolded data, generated gold, proposed thresholds, and uncalibrated judges start
  informational and cannot gate.
- **Epistemic core.** Wilson / Student-t `Estimate`s with confidence intervals, a `DecisionPolicy`
  (lower-confidence-bound gating, `min_n_effective`, `max_missing_fraction`), capability-typed
  authority (a fake judge can never gate), digest-bound `AuthorityGrant`, computed
  `JudgeAgreementStudy`, content-addressed `JudgeInstrument`, and an optional `ClaimSpec`.
- **Provenance and baseline comparability.** Structured fingerprint dimensions (framework, metric,
  evaluator, aggregation, dataset/reference, example, evidence, judge/rubric/model, runtime config,
  data policy, threshold, authority). Baseline state is a typed claim
  (`comparable`/`not_comparable`/`missing_baseline`/`comparison_not_requested`); a regression without
  comparability is not a claim.
- **Typed paired comparison as primary truth.** A run persists a typed `ComparisonResult` on its
  Scorecard — the single carrier of "did quality change". A numeric per-metric delta exists only when
  the run is `comparable`; a `not_comparable` run records the changed fingerprint dimensions and no
  delta. `MetricDelta` carries a `direction_adjusted_delta` (re-signed so positive is always
  improvement); pairing is by shared `example_id`; an interval crossing zero is `within_noise`.
  Comparison is evidence, not a verdict — it sets no `ci_should_fail` and no exit code, and its state
  must match the Scorecard's `baseline_state`.
- **First-class per-metric population accounting.** Each metric persists a typed `PopulationSummary`
  reconciling pre-effect coverage (available / selector-matched / eligible) with terminal measurement
  states (scored_valid / non_evaluable / blocked / skipped / error), so a metric that validly scored
  1 of 100 eligible subjects can no longer read as fully covered. The terminal layer is a verified
  projection (a tampered count fails to load) and it is coverage, not a quality composite.
- **Metric-scoped authority and source bindings.** A metric may declare `sources: [{name, role}]`
  (`candidate`/`reference`/`context`/`observation`) so its executed population comes from the sources
  its construct actually consumes; bindings resolve fail-closed and are score-determining. A bound
  metric resolves its dataset status and data policy over only the sources it consumes, so an
  unrelated proposed or forbidden source no longer dilutes it. An unbound metric keeps the
  conservative run-global worst.
- **Diagnostic clusters.** A run's failing / non-scored items are grouped by their shared
  `Diagnostic.code` into a typed, per-metric cluster view, computed effect-free and recomputed on
  load (a hand-edited cluster fails closed). It adds explanatory structure only and never changes a
  verdict.
- **Deterministic, domain-neutral built-in evaluators** — exact match, field presence, numeric
  bounds, set overlap, enum membership, structural / trajectory shape, word-count bounds, and a judge
  score parser — each versioned, registry-declared, and diagnostic on non-scored states.

#### Runtime Harness (owns effects through visible ports)

- **CLI and typed config boundary.** `evalglass` verbs `setup`, `connect`, `run`, `view`, `explain`,
  `compare`, `baseline`, `watch`, `preflight`, `assemble`, `series`, and `ci`; config errors become
  setup diagnostics, not evaluator scores; YAML is read with `safe_load`.
- **Plan-before-effects control plane.** A typed, JSON-serialisable `EvaluationPlan` is resolved
  before any effect and drives scoring, judge collection, and replay from one applicability decision;
  judge evidence is collected only for the plan's eligible judge effects, bounding external egress.
  `evalglass preflight` and `run --dry-run` resolve the same plan a real run would and report, per
  metric, the eligible population, planned judge / replay request counts, the egress decision, and
  whether a gate would be authorized if measured — performing no provider / judge / replay / egress
  and emitting no verdict.
- **Ports and MVP adapters.** `DatasetStore`, `TraceSource`, `TaskRunner` (subprocess JSON in/out),
  `JudgeModel`, `ResultStore`, and `ScoreSink`, with local-JSONL and filesystem adapters. JSONL is
  the canonical local route; subprocess stdout / stderr / exits / timeouts become typed evidence;
  data policy is enforced before effects.
- **Immutable run-series index and honest progression.** Each distinct run (keyed by a content
  digest) is snapshotted with manifest + completion-marker integrity and recorded in an append-only,
  crash-safe, repairable index; rerunning a fixed name never erases prior evidence. A `series` verb
  (`list`, `repair`) rebuilds the index from the snapshots on disk, promoting no baseline and changing
  no verdict.
- **Continuous drift watcher.** `evalglass watch` runs one evaluation, compares it to the configured
  baseline, records a typed `drift.json`, and exits (scheduled re-invocation, not a resident daemon).
  A `regression` is flagged only when the runs are `comparable` and the paired interval clears zero;
  it adds no exit class and never promotes the baseline.
- **Config-reachable unit ladder.** A `traces:` route may declare `unit: trajectory` (or
  `session` / `step`) to grade the whole agent run; an aggregate's egress is the worst of its members
  (one forbidden member blocks it). Aggregates run over proposed trace data, so they stay
  informational and cannot gate.
- **Diagnostic-first dashboard, rendered from a typed projection.** The default `report.html` is a
  quiet, diagnostic-first dashboard — a verdict hero and authority strip, evaluability KPIs, workflow
  coverage bars (never an implicit quality mean), a comparable-only paired-delta forest plot,
  descriptive progression, a typed attention queue, and a searchable metric explorer with expandable
  call and judge evidence. It renders from a versioned, score-neutral projection
  (`evalglass.dashboard/1`, written as `dashboard.json`) that copies verdict, authority, gate state,
  population, interval, and comparison from the typed artifacts and computes none of them. A
  non-scored metric renders as absence, never a 0; an informational run is never styled as a pass. The
  report is self-contained (inline CSS/JS, `data:` favicon, a restrictive CSP, no network) and works
  from `file://`. A `report.md` renders the same facts from the same typed data.

#### Authoring metrics (host-directed)

- **You decide what to measure; the agent scaffolds it.** EvalGlass supplies the metric vocabulary,
  the deterministic built-in evaluators, and the host-evaluator seam, and lets the host decide what to
  check. `authoring-a-metric` turns a named check into a `MetricSpec` in `evals/evalglass.yaml` across
  three tiers (runtime / reference / judge); `writing-a-host-evaluator` scaffolds a host-owned scorer
  that imports only the vendored contracts. Every scaffolded asset lands `proposed` / `informational`
  / `uncalibrated` and cannot gate until the host validates gold, approves a threshold, and (for
  judges) calibrates. The framework derives no metrics on its own.

#### Judges and rubrics

- **Configure a real OpenAI-compatible judge directly.** `judge.adapter: openai_compatible` selects
  an OpenAI-compatible `/chat/completions` judge (OpenAI, OpenRouter, or a local server) on the same
  evidence route as `fake`/`command`. The credential is an environment-variable *name*, resolved only
  at effect time and never stored in config, plan, provenance, or any artifact; egress is HTTPS-only
  except an explicit loopback policy. The adapter is imported lazily so a fake / no-judge run stays
  hermetic, and the required tier ships no provider SDK. A real judge stays informational until the
  host calibrates it.
- **Host command judge.** `SubprocessJudgeModel` runs a host judge inside `evalglass run` over a JSON
  contract (`shell=False`); every failure edge is non-`OK` evidence with no value. Uncalibrated →
  informational.
- **Structured, versioned rubrics and a structured judge result.** A rubric can be a typed
  `RubricSpec` (`evalglass.rubric/1`): a construct, ordered anchored criteria, a declared evidence
  boundary, refusal conditions, and a response schema. A parser distinguishes a valid score from a
  refusal, missing evidence, or a parser error, rejects any undeclared facet, and resolves cited
  evidence refs against the dossier (an invented citation is a parser error). A new rubric is
  `proposed` and grants no authority.
- **Bounded, reproducible judge execution.** A typed `judge.execution` policy adds a deterministic
  local cache (keyed by the score-determining instrument + request content, never a secret),
  budgets (`max_requests` / `max_total_tokens` / `max_cost` / `max_wall_seconds`) checked before each
  dispatch, and bounded retry with injected backoff. The framework embeds no prices; the default
  policy is a no-op.
- **Complete judge evidence persisted in the run.** The archived `RunRecord` carries the parsed judge
  evidence (score, rationale, facets, violations, citations, instrument refs, usage) that produced
  each judge `Score`, resolvable via `RunRecord.resolve_evidence(...)` and integrity-covered. The raw
  provider text is dropped by default and kept only when a host sets `judge.retain_raw_response`.

#### Optional lanes and connected evidence

- **Opt-in, deletable connectors and judge lanes.** Langfuse / Phoenix / LangSmith trace connectors
  and an OpenAI-compatible judge lane sit behind ports as opt-in, pinned, deletable optional lanes; no
  required import path loads a lane, and a missing extra / credential is a clean `SKIPPED`. Evidence
  from a lane can inform diagnostics but never overrides authority, and a live pull is `proposed` data
  that cannot gate.
- **Complete and reproducible connected evidence.** `evalglass connect --from <export> --format
  <local|opentelemetry|openinference>` registers an exported trace file as a first-class `traces:`
  route with no credentials and no provider SDK; `connect --live <platform>` scaffolds a fail-closed,
  credentials-as-env-var-names connector lane (egress refused until `data_policy: permitted`). Every
  source read produces one typed coverage manifest with a typed completeness, persisted off the
  Scorecard, so an empty or partial import can never look complete. `evalglass assemble` runs a
  declarative `evidence_pipeline` (named local sources, typed joins with cardinality, a
  behavior-preserving projection) into ordinary Example JSONL plus a lineage/digest manifest.
- **Proposed-reference lifecycle.** `draft -> proposed -> reviewed -> validated -> retired`, with
  leakage refusal and no agent / author self-approval — EvalGlass verifies a host review record, it
  never writes `validated`.

#### Packaging, delivery, and tooling

- **Dual-runtime plugin.** A single-plugin marketplace installed with
  `/plugin marketplace add EvalGlass/evalglass-core` then `/plugin install evalglass-core@evalglass`.
  The `/evalglass` umbrella (skill-based, with a natural-language router and an always-on honesty
  narration guardrail) exposes one command with verbs; the backing skills auto-trigger by description.
  The same canonical `skills/` tree packages both the Claude Code (`.claude-plugin`) and Codex
  (`.codex-plugin`) runtimes with no forked guidance. `bin/evalglass-launch` runs the bundled
  framework so a marketplace-only user needs no `pip install`.
- **Installer and vendoring boundary.** `python -m evalglass.installer install` discovers a host repo
  conservatively (a read-only call-site inventory), vendors managed runtime files under
  `evals/_evalglass/`, writes a manifest and lock, scaffolds host-owned eval assets, and supports a
  dry-run re-vendor. Managed runtime is separated from host-owned truth; the runtime works after the
  plugin and coding-agent context are removed.
- **Single-source versioning.** `.version-bump.json` + `scripts/bump-version.sh`
  (`--check` / `--audit` / `--set`) keep every version-bearing surface aligned;
  `scripts/sync-to-codex-plugin.sh` keeps the Codex manifest deterministic.
- **Repository trust tooling.** A diff-aware scan gate and a semantic overclaim validator gate
  (shipped as development skills) check changed code for trust-policy violations that generic CI
  cannot see. A hermetic test spine with a no-network guard, a dependency budget, a core-isolation
  check, architecture decision records, worked examples, and an EvalGlass proof suite back the
  no-false-confidence rule. `main` enforces green-before-merge via the full required-check set
  (static analysis, tests on Python 3.12 / 3.13, docs-consistency and public-surface snapshot guards,
  the gate suites, and the supply-chain / secret scans); SonarCloud stays informational
  ([ADR 0004](adrs/0004-sonarcloud-informational.md)).

### Notes / limitations

- A fresh run is **informational** by design — real non-reference signal, but not a quality pass;
  gating requires host-validated gold, an approved threshold, and (for judges) calibration.
- **Automated metric discovery is intentionally out of scope.** The core gives you the framework; you
  direct the agent to author the metrics your app needs. EvalGlass never derives metrics from an app's
  traces, prompts, or schemas on its own — the host decides what to measure.
- Optional lanes (live trace connectors, real-provider judges) are opt-in, pinned, and deletable; no
  required path imports them and no required test uses a live provider. Synthetic-data *generation*
  ships no generator by design (governance-only).
- Tagging and any PyPI / marketplace publishing are deliberate maintainer steps, not automated.

[0.2.1]: https://github.com/EvalGlass/evalglass-core/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/EvalGlass/evalglass-core/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/EvalGlass/evalglass-core/releases/tag/v0.1.0
