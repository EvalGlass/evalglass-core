# EvalGlass vocabulary

The canonical terms. One name per concept; the skills and reference use these exactly. (Banned as
architecture terms: *kernel*, *test kernel*, *pure kernel* — say **Evaluation Core** / effect-free
core instead.)

## Product framing

- **AI quality-control tool** — what EvalGlass *is*: an AI quality-control loop you operate through
  a coding agent, turning real LLM behavior into project-specific checks and a bounded scorecard. It
  reports only what the evidence honestly supports; it is not a hosted platform and makes no quality
  guarantee.
- **coding agent** — the agent (Claude Code / Codex) that discovers call sites, scaffolds checks,
  runs the vendored runtime, and explains results. It never grants authority.
- **project-specific checks** — the host-authored metrics, examples, rubrics, and judges that make
  the evaluation meaningful for *this* app. They start proposed until the host validates them.

## Layers

- **Evaluation Core** — the effect-free, standard-library-only center: contracts, score semantics,
  aggregation, provenance, authority, baseline comparability, and the Verdict Engine. No I/O.
- **Runtime Harness** — the effectful layer: CLI, config, adapters/ports, replay, judge-evidence
  collection, persistence, reports, CI exit mapping. Owns effects, not meaning.
- **EvalGlass Skill** — the integration-time installer (discover / plan / install / re-vendor).
  Grants no authority; not needed at runtime.
- **Host-owned truth** — datasets, references, rubrics, calibration, approved thresholds, baselines,
  host evaluators, and domain approvals. The host owns these.

## Data spine (input convergence)

- **TraceEnvelope** — vendor-neutral normalized host behavior + metadata, data policy, provenance.
- **EvalUnit** — a declared behavior slice (call-level in MVP; step/trajectory/session later).
- **Example** — an evaluator-ready item: input, output, optional reference, context, unit, provenance.
- **EvidenceBundle** — references, source/judge/verifier evidence, runtime errors, trace fragments.

## Measurement

- **MetricSpec** — a metric's declared meaning: lens, score type, direction, prerequisites, evidence
  needs, aggregation, threshold, authority, data policy.
- **Lens** — **reference** (compare to gold: *is it correct?*) vs **non-reference** (input + output
  only: *is it well-formed / grounded?*).
- **Score** — one metric result: value, **status**, **validity**, diagnostics, evidence refs,
  evaluator version, provenance.
- **Score status** — `scored` · `blocked` · `non_evaluable` · `skipped` · `error`. Only `scored` +
  `valid` enters aggregation; the others are **never** encoded as `0.0`.
- **Score subject identity** — `example_id`/`unit_id` carried by each Score (framework slice F1):
  which Example/EvalUnit it measured. **Additive provenance, not meaning** — it lets a reader group
  scores per call; it is never authority or source-function attribution.
- **Diagnostic** — structured explanation (code, severity, message, location, cause, evidence refs).

## Trust & outcome

- **Authority** — typed evidence (dataset status, metric status, threshold approval, judge
  calibration, data policy, baseline comparability) that a score may *gate*. Not report prose.
- **Provenance** — structured per-dimension fingerprints carried by every score and run.
- **Baseline comparability** — a typed claim: `comparable` · `not_comparable` · `missing_baseline`
  · `comparison_not_requested`. No comparable fingerprint → no regression claim.
- **Verdict Engine** — the *single* path that turns scores + authority into a run outcome.
- **Verdict** — `informational` · `pass` · `fail` · `blocked`, plus `ci_should_fail`.
- **RunRecord** — the complete machine-readable record of a run. **Scorecard** — the compact,
  authority-aware summary. Both are primary; `report.md` is a rendering.

## Plugin surface

- **`/evalglass <verb>`** — the umbrella: `setup`, `connect`, `run`, `view`, `explain`, `compare`,
  `baseline`, `ci`. Bare `/evalglass` is an honest status overview.
- **`view` granularities** — **per-metric** (default) · **per-call** (`--by-call`, grouped by Score
  subject identity, never by list order) · **per-source-function** (advanced, not yet — needs
  trace↔call-site correlation that does not exist).
- **Vendoring** — the skill copies only `core`/`harness`/`adapters` into `evals/_evalglass/`; the
  runtime then runs independently of the plugin and any agent.
