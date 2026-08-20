# AGENTS.md - EvalGlass Implementation

This is the operating guide for agents implementing EvalGlass itself. The
EvalGlass Testing System has its own AGENTS file; do not copy its testkit rules
into product runtime code.

EvalGlass is a small, vendored, local-first evaluation framework for LLM
applications. It measures quality and trust signals from host-owned evidence,
then reports what EvalGlass can honestly claim. It does not improve the host
application, replace domain judgment, or become a hosted platform.

The central rule is no false confidence:

> A green or non-failing EvalGlass result must never imply more evidence,
> authority, comparability, calibration, or safety than the run actually has.

## 1. Source Of Truth

Read in this order before making implementation decisions:

1. `AGENTS.md` - this file.
2. `EvalGlass_Design_Principles.md`
3. `EvalGlass_System_Architecture_Build_Contract.md`
4. `EvalGlass_Evaluation_Core_Architecture.md`
5. `good/EvalGlass_System_Architecture_Build_Contract_Jira_Epics_Tickets.xlsx`
6. `EvalGlass_Open_Source_Tooling_Research.md`
7. `EvalGlass_Testing_System_Architecture_Build_Contract.md`
8. `good/AGENTS_test.md`
9. `good/AGENTS_evalglass_implementation_uncompressed.md`

The product Jira Excel workbook contains current implementation-ticket
guidance. The uncompressed AGENTS draft is reference material, not a second
authority. Treat stale Atlassian tickets, old drafts, and conversation memory as
background only.

If sources conflict, protect these first: measurement integrity, Verdict Engine
ownership, typed authority, provenance, baseline comparability, CI exits,
vendoring boundaries, optional-lane deletion, and public JSON contracts. Record
the decision instead of silently choosing.

Architecture and tooling decisions that are public-facing or hard to reverse are
recorded as **Architecture Decision Records** under `adrs/` (index + criteria in
`adrs/README.md`). Read the relevant ADR before changing what it governs, and add
a new `adrs/NNNN-slug.md` when you make such a decision. The current per-milestone
plan and slice tracker are kept as a local working document
(`docs/IMPLEMENTATION_PLAN.md`, no longer committed); the durable public record of
what shipped is `CHANGELOG.md` and `adrs/`.

## 2. North Star

EvalGlass lets a small-to-medium agentic project measure and improve the
quality of its LLM calls with minimal ceremony, and grow that capability as its
needs deepen.

Hold these design commitments:

- Generic by contract: no domain knowledge in the managed framework spine.
- Minimal and expandable: core first, optional rings later.
- Trustworthy: honest measurement beats broad weak coverage.
- Open and skill-delivered: vendored source, no hosted runtime dependency.
- Host-owned truth: the host validates gold, rubrics, thresholds, calibration,
  baselines, and domain evaluators.
- EvalGlass supplies evaluation methodology; the host supplies domain judgment.

When principles conflict, resolve in this order:

1. Trustworthiness over coverage.
2. Minimalism over completeness for the core.
3. Host autonomy over framework opinion.
4. Genericity over convenience for the spine.
5. Predictability over configurability.
6. Evaluation validity over performance.
7. Clean extension seams over baked-in features.

## 3. Product Scope

Build EvalGlass as a framework, not a platform. The MVP must run locally and in
CI from vendored source in a host repo.

The required MVP path is:

```text
local JSONL dataset or trace
  -> Runtime Harness
  -> TraceEnvelope / EvalUnit / Example
  -> Evaluation Core
  -> RunRecord JSON + Scorecard JSON
  -> Markdown report + CI annotations + exit code
```

The product claim is:

```text
Given the supplied evidence, authority records, metrics, thresholds,
calibration, baselines, and data policy, EvalGlass can honestly emit this
Scorecard and verdict.
```

Do not make the MVP depend on hosted services, live models, tracing vendors,
provider SDKs, dashboards, Docker, workflow engines, or optional ecosystem
tools.

## 4. Non-Negotiables

1. Only the Verdict Engine decides `pass`, `fail`, `blocked`, or
   `informational`.
2. The Evaluation Core is effect-free and standard-library-only.
3. Runtime Harness owns effects, not meaning.
4. The EvalGlass Skill runs at integration time only.
5. Score value is not score validity.
6. Authority is typed data, not report prose.
7. Baseline comparability is a typed claim, not a previous score lookup.
8. Scorecard JSON and RunRecord JSON are primary. Markdown is rendered from
   typed data.
9. Dataset replay, trace import, subprocess replay, and future routes converge
   through `TraceEnvelope -> EvalUnit -> Example`.
10. Scaffolded data, generated gold, proposed thresholds, placeholder rubrics,
    and agent edits start informational.
11. Judge metrics cannot gate until calibrated.
12. Reference metrics cannot gate on proposed or retired datasets.
13. CI exits derive from the core verdict payload only.
14. Optional integrations are opt-in and deletable.
15. No optional package may be imported by required product paths.
16. No report, CLI, adapter, sink, skill, or test code may manufacture
    authority.

## 5. Required Vocabulary

Use these names consistently:

- `Evaluation Core`: effect-free runtime center for contracts, score semantics,
  aggregation, provenance, authority, baseline comparability, and the Verdict
  Engine.
- `Runtime Harness`: effectful layer for CLI, config, adapters, task replay,
  judge calls, persistence, reports, and CI exit mapping.
- `EvalGlass Skill`: integration-time installer that discovers a host repo,
  vendors managed files, scaffolds host-owned assets, wires CI, and asks for
  validation.
- `Host-owned truth`: datasets, references, rubrics, calibration, approved
  thresholds, baselines, host evaluators, and domain decisions.
- `TraceEnvelope`: vendor-neutral normalized host behavior plus metadata, data
  policy, and provenance.
- `EvalUnit`: declared behavior slice: call in MVP; step, trajectory, and
  session later.
- `Example`: evaluator-ready item with input, output, optional reference,
  context, unit, metadata, and provenance.
- `EvidenceBundle`: references, source material, judge evidence, verifier
  evidence, runtime errors, and trace fragments collected by the Runtime
  Harness.
- `MetricSpec`: declared metric meaning: lens, score type, direction, profile,
  evidence needs, prerequisites, aggregation, threshold, authority, data policy.
- `Score`: one metric result with value, status, validity, diagnostics,
  evidence refs, evaluator version, and provenance.
- `RunRecord`: complete machine-readable record for a run.
- `Scorecard`: machine and human summary with metric summaries, diagnostics,
  authority explanation, baseline state, and Verdict Engine output.

Do not use `kernel`, `test kernel`, or `pure kernel` as public architecture
terms. Use `Evaluation Core`, `effect-free core`, and `core isolation`.

## 6. Layer Boundaries

| Area | Owns | Must not own |
|---|---|---|
| Evaluation Core | Meaning, contracts, score states, registry, evaluator protocol, aggregation, provenance, authority, baseline comparability, Verdict Engine, JSON schemas. | File I/O, network I/O, subprocesses, clocks, randomness, env access, model calls, vendor SDKs, config loading, report rendering, CI exits, domain correctness. |
| Runtime Harness | CLI, config, local adapters, ports, route convergence, replay, judge calls, persistence, reports, CI annotations, exit mapping. | New score meanings, ad hoc verdicts, hidden authority, host approval. |
| EvalGlass Skill | Discovery, install plan, vendoring, manifest, lock file, scaffolds, CI snippets, confirmation checklist, re-vendoring support. | Runtime execution, metric authority, domain approval, automatic gating, hidden host mutation. |
| Host-owned truth | Examples, references, rubrics, thresholds, calibration, baselines, evaluator code, approvals. | Managed framework internals. |

Imports should reflect the boundary. Core must not import runtime, adapters,
skill code, host code, testkit code, optional lane packages, or provider SDKs.

## 7. Host Layout

The skill installs EvalGlass into a host repo with managed runtime files
separated from host-owned truth.

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

Rules:

- `_evalglass/` is managed runtime.
- Host-owned truth stays outside `_evalglass/`.
- Re-vendoring may replace managed files only.
- Host patches to managed files must be visible in the manifest.
- The skill may scaffold host-owned files, but human validation is required
  before they create gating authority.
- Runtime must work after the skill and coding-agent context are removed.

## 8. Evaluation Core

Build M0 core in small tested slices: public contracts, diagnostics, score
model, metric registry, evaluator protocol, prerequisites, aggregation,
provenance, authority, baseline comparability, Verdict Engine, minimal
built-ins, and public JSON snapshots.

Core data flow:

```text
TraceEnvelope
  -> EvalUnit
  -> Example
  -> MetricSpec + EvidenceBundle
  -> Evaluator
  -> Score | ScoreBatch
  -> AggregatedMetric
  -> Provenance + Baseline Comparability
  -> ResolvedAuthority
  -> Verdict
  -> RunRecord + Scorecard
```

Allowed core tools: `dataclasses`, `enum`, `typing`, `json`, `hashlib`, and
`decimal` only if exact threshold arithmetic needs it.

Forbidden in core: third-party validation/config/reporting libraries, vendor
SDKs, observability packages, external eval frameworks, optional lane packages,
file/path effects, network, subprocesses, model clients, clocks, randomness,
environment access, and hidden global state.

Built-in evaluators must be deterministic, domain-neutral, versioned,
diagnostic, registry-declared, and effect-free.

## 9. Score Semantics

Status and validity are explicit.

| Status | Meaning | Aggregation |
|---|---|---|
| `scored` | Metric produced a meaningful value. | Include only when validity is `valid`. |
| `blocked` | Required metric could not honestly run. | Exclude from math; blocks active gates. |
| `non_evaluable` | Example lacks meaningful evidence for the metric. | Exclude from math; blocks if required. |
| `skipped` | Metric intentionally not run. | Exclude; may block if required. |
| `error` | Evaluator or evidence parser failed unexpectedly. | Exclude; blocks active gates. |

Validity values:

- `valid`
- `invalid`
- `not_measured`
- `not_applicable`

Never encode blocked, skipped, errored, or non-evaluable as `0.0`. Invalid or
missing measurement is not bad quality.

Every non-perfect or non-measured state should carry structured diagnostics:
code, severity, message, location, details, cause, and evidence refs.

## 10. Metrics And Evaluators

`MetricSpec` must declare:

- name/version, lens, granularity, score type/range/direction, evaluator ref,
  profile, required evidence, prerequisites, aggregation, threshold, authority,
  and data policy.

Registry rules:

- emitted score names and batch members are declared;
- types, ranges, directions, and aggregation rules are valid;
- evaluator refs, evaluator versions, effect requirements, and authority
  requirements are explicit.

Evaluator protocol:

```python
Evaluator(example, context, evidence) -> Score | ScoreBatch | RawMeasurement
```

Evaluators receive data, not adapters. Runtime calls models and verifiers before
core execution, records evidence, and passes that evidence into the core.

## 11. Provenance, Authority, And Verdicts

A score without provenance is not interpretable. A regression without
comparability is not a claim.

Fingerprint structured dimensions, not just opaque hashes:

- framework, metric, evaluator, aggregation, dataset/reference, example,
  evidence, judge/rubric/model, runtime config, data policy, threshold, and
  authority dimensions.

Baseline states:

- `comparable`
- `not_comparable`
- `missing_baseline`
- `comparison_not_requested`

Authority is typed data: dataset status, metric status, threshold approval,
judge calibration, and data-policy state are all explicit inputs to authority
resolution.

Only the Verdict Engine turns score and authority state into a run outcome:

- no active gates -> `informational`, `ci_should_fail=false`;
- active gate blocked or missing required evidence -> `blocked`,
  `ci_should_fail=true`;
- active gate validly measured below approved threshold -> `fail`,
  `ci_should_fail=true`;
- all active gates valid, comparable where required, and passing approved
  thresholds -> `pass`, `ci_should_fail=false`.

Runtime may translate `ci_should_fail` into an exit code. It must not compute
its own verdict.

## 12. Runtime Harness

Runtime owns effects through visible ports:

| Port | Purpose | MVP adapter |
|---|---|---|
| `DatasetStore` | Read examples, references, dataset status, version. | Local JSONL. |
| `TraceSource` | Yield recorded host behavior. | Local JSONL. |
| `TaskRunner` | Replay host outputs when needed. | Subprocess JSON in/out. |
| `JudgeModel` | Collect judge evidence when declared. | Fake required-tier judge. |
| `ResultStore` | Persist RunRecords, Scorecards, reports, baselines. | Filesystem JSON/JSONL. |
| `ScoreSink` | Present immutable results. | Markdown, JSON, CI annotations. |

Runtime rules:

- Config errors become setup diagnostics, not evaluator scores.
- Use `yaml.safe_load` if YAML is used.
- Keep Pydantic/jsonschema at the config boundary only if justified.
- JSONL is the canonical local MVP route.
- Trace backends come later through adapters.
- Subprocess stdout, stderr, exits, and timeouts become typed evidence.
- Data policy is enforced before effects.
- Reports render from Scorecard/RunRecord only.
- ScoreSinks consume immutable data and do not mutate verdicts.
- Baseline updates require explicit command or workflow.

## 13. Skill And Vendoring

The EvalGlass Skill is integration-time only.

Skill responsibilities:

- discover conservatively, plan install, vendor managed files, write manifest
  and lock, scaffold host-owned eval assets, wire CI snippets, produce first-run
  guidance, and support dry-run re-vendoring.

Skill rules:

- no runtime dependency on the skill;
- no automatic domain approval;
- no hidden host file mutation;
- generated gold stays provisional;
- generated thresholds stay proposed;
- generated judge rubrics stay uncalibrated;
- dry-run diff before re-vendoring;
- preserve host-owned files;
- report conflicts instead of guessing.

Use conservative discovery first: globs, ignore handling, and Python AST.
Consider LibCST only for formatting-preserving edits and tree-sitter only for
later cross-language discovery.

## 14. Judges And Optional Lanes

Judge flow:

```text
Runtime Harness calls JudgeModel
  -> records JudgeEvidence
  -> core evaluator parses/scores evidence
  -> core resolves calibration and authority
```

Required flows use fake judge evidence only. Live models belong to optional
lanes.

Optional lane candidates include OpenTelemetry/OpenInference traces, Phoenix,
Langfuse, Promptfoo, garak, Ragas, DeepEval, MLflow, Ollama, LangGraph,
Temporal, annotation, synthetic data, and trajectory/session support.

Optional lane rules:

- opt-in only;
- removable;
- dependencies isolated and pinned;
- no required import path loads the lane;
- evidence may inform diagnostics but cannot override authority;
- ScoreSink failures cannot hide or change the core verdict;
- deletion verification must leave required tests green.

## 15. Tooling Policy

Do not replace EvalGlass with an external eval framework.

Use open-source tools around EvalGlass:

- Core: standard library only.
- Runtime: `argparse` or Typer, PyYAML `safe_load`, Pydantic/jsonschema at the
  boundary, Jinja2/Rich only if justified.
- Framework repo: `uv`, Ruff, Pyright or mypy, nox if useful, pip-audit,
  detect-secrets, Semgrep, import-boundary checks.
- Tests: pytest, Hypothesis where useful, no-network guard, snapshots, JSON
  evidence reports.

Supply-chain rules:

- required dependencies are pinned;
- optional AI infrastructure packages are isolated;
- host scaffolds do not add provider SDKs by default;
- record dependency source/version in lane evidence.

## 16. Milestone Guidance

Use the Jira workbook for exact ticket scope. Keep this milestone intent:

| Milestone | Implement | Guardrail |
|---|---|---|
| M0 Core | Contracts, diagnostics, scores, registry, evaluators, aggregation, provenance, authority, baseline comparability, Verdict Engine, snapshots. | Stdlib-only, effect-free, JSON-compatible, no duplicate verdict path. |
| M1 Runtime | CLI/config boundary, JSONL dataset/trace routes, route convergence, evaluator loading, ResultStore, Scorecard JSON, Markdown reports. | Harness owns effects only; fresh scaffolds stay informational. |
| M2 Replay/CI | Subprocess replay, structured baseline fingerprints, data policy, CI annotations, exit mapping. | Exit derives only from core `ci_should_fail`; no live services required. |
| M3 Skill | Conservative discovery, vendoring, manifest, lock file, safe scaffolds, CI snippets, confirmation checklist, re-vendor flow. | Generated assets are non-authoritative; runtime works after skill removal. |
| M4 Judges | JudgeModel port, fake judge evidence, rubric provenance, calibration records, approved thresholds, drift/malformed cases. | Live providers are optional; judge metrics gate only when calibrated. |
| M5 Extensions | Optional lane framework, trace backends, ScoreSinks, annotation, synthetic data, trajectory/session support. | Every lane is isolated, pinned, opt-in, and deletable. |

## 17. Testing Expectations

Product tests must prove real product behavior, not EGTS internals.

Required product coverage:

- Core isolation, score status/validity tables, registry conformance, evaluator
  contract, prerequisites, aggregation, provenance/baselines, authority/verdict
  matrix, and public JSON snapshots.
- Runtime JSONL dataset route, JSONL trace route, route convergence, setup
  diagnostics, fake judge evidence, subprocess replay, data-policy refusal,
  report rendering, and CI exit mapping from core payload.
- Skill fixture install, manifest/lock creation, safe informational defaults,
  host-owned file preservation, managed-file patch detection, re-vendor dry-run,
  conflict reporting, and runtime after skill removal.

EGTS will later prove the same claims through real product surfaces. Leave
stable JSON artifacts and diagnostics for it to inspect.

## 18. Change Rules

Use these local rules when changing the implementation:

- Core contract: belongs to meaning, stays JSON-compatible, gets invalid-state
  and round-trip tests, and is snapshotted if public.
- Built-in evaluator: domain-neutral, MetricSpec-declared, deterministic,
  diagnostic, and tested for non-scored states.
- Runtime adapter: uses an existing port if possible, keeps SDK imports outside
  required paths, converts external shapes immediately, and never emits scores,
  authority, or verdicts.
- Gating change: touches authority resolution or Verdict Engine only, adds
  matrix tests, updates JSON snapshots, and checks for duplicate CLI/report/sink
  logic.
- Skill scaffold: chooses managed vs host-owned first, manifests managed files,
  keeps generated host truth non-authoritative, and adds validation checklist
  items.
- Optional lane: isolates dependencies, proves required imports do not load it,
  adds deletion verification, and records dependency/evidence metadata.
- Hard-to-reverse decision: a new dependency, public-API/CLI/report-schema change,
  verdict/authority-mapping change, port/adapter or host-layout change, or a
  build/test/release tool swap is recorded as an ADR under `adrs/`
  (`adrs/README.md` lists when and how); reference its number in the slice.

## 19. Reject

Reject these shortcuts:

- domain knowledge, hidden host metric discovery, or external eval frameworks in
  the managed core;
- score `0.0` for blocked/skipped/error/non-evaluable states;
- verdict logic outside the Verdict Engine;
- judge network calls inside core evaluators;
- baseline deltas without comparability;
- proposed datasets, proposed thresholds, generated gold, or generated rubrics
  becoming authority;
- uncalibrated or drifted judges failing CI;
- report prose carrying authority missing from Scorecard data;
- optional lane packages in required imports or live providers in required
  tests;
- auto-tuning prompts/models from inside EvalGlass;
- silent host-owned file mutation.

## 20. Definition Of Done

A change is done only when:

- boundaries are preserved;
- public contracts are JSON-compatible;
- status, validity, authority, provenance, and baseline comparability are typed;
- the Verdict Engine is the only verdict path;
- reports render from Scorecard/RunRecord data;
- CI exits derive from `ci_should_fail`;
- required tests are hermetic;
- optional dependencies are isolated and deletable;
- host-owned files are preserved;
- scaffolds stay informational until validation;
- ticket guidance and EGTS proof expectations are reflected.

Final question:

```text
Could a green Scorecard be misread as proof of correctness when the run is only
informational, unvalidated, uncalibrated, non-comparable, non-evaluable, or
partly blocked?
```

If yes, the implementation is not finished.

## 21. Implementation-Loop Lessons

Build in slices (one slice = one PR): tests-first (red→green) → scan → review → PR
→ CI → squash-merge. These five were learned the expensive way on the Scan Gate and
Validator Gate builds; apply them to every slice-based build.

1. A gate that cannot see its target is false confidence, not safety. The Scan
   Gate returned `PASS / 0 findings` on 38+ real runs — not because code was clean,
   but because it was outside the gate's path scope and the product code it guards
   does not exist yet: a 0-for-0 record dressed up as a clean pass. Run a gate only
   against artifacts in its jurisdiction; when the jurisdiction is empty, report *not
   exercised*, never `PASS`. This is the no-false-confidence rule applied to our own
   tooling.

2. Code review is the real defect-catcher — and the biggest time sink. The Codex
   review step found genuine fail-closed bugs in almost every slice (malformed input,
   missing/duplicate artifacts, ambiguous refs, symlink-following, table injection,
   evidence-free PASS) that tests-first had missed. But waiting on it serialized every
   slice and dominated build time. Keep it, and make it cheap: scope it to the
   committed slice diff (`codex review --commit HEAD`, not `--base`), don't block the
   whole loop on it, and pre-empt it by writing the fail-closed / malformed / adversarial
   cases into tests-first so there is less left for review to catch.

3. Never run parallel agents in a shared working tree. Concurrent agents in one
   checkout lost a slice's review fixes to a branch switch (recovered only as a
   follow-up PR) and cut a branch from the wrong base (forcing a rebase). Use an
   isolated git worktree per agent/task, and verify the merged commit actually
   contains the fixes — green CI on the wrong branch is a lie.

4. "CI green" is not "the change was tested." GitHub CI excludes `.claude/**`, so it
   never ran the skills' own suites; the local per-slice `pytest` was the only real
   gate. Always confirm the suite that proves a change actually runs somewhere — a
   green check that skips your code proves nothing.

5. Scope every per-slice review and scan to the committed slice diff, not the dirty
   tree. Reviewing the working tree repeatedly pulled in unrelated in-flight changes,
   forcing the same out-of-scope triage each slice. Commit the slice first, then
   review/scan `origin/main..HEAD`.

## 22. Commit And PR Convention

All commit subjects and PR titles MUST follow one format, so the history reads
consistently across every build. The PR title and the final squash-merge commit
subject are identical; GitHub appends the ` (#NN)` PR number on squash.

**Title format:**

```text
<type>(<scope>): <summary> (<MILESTONE> Slice <n>, <TICKET[/TICKET2]>)
```

- `<type>`: one of `feat`, `fix`, `test`, `docs`, `ci`, `chore`, `refactor`, `perf`.
- `<scope>`: the owning component — `core`, `harness`, `adapters`, `skill`, `egts`,
  `scan-gate`, or `validator-gate`. Omit the scope only for repo-wide changes
  (e.g. `ci: …`).
- `<summary>`: imperative, lower-case, no trailing period, ≈65 chars before the
  parenthetical.
- Trailer `(<MILESTONE> Slice <n>, <TICKET>)` ties the change to the slice table in
  the local `docs/IMPLEMENTATION_PLAN.md` working doc and the Jira ticket(s); join multiple tickets with
  `/`. Drop the trailer only for out-of-band fixes that belong to no slice.

**Examples (consistent with merged history):**

```text
feat(core): single Verdict Engine + verdict matrix (M0 Slice 7b, EG-M0-5b)
feat(harness): CLI + typed config boundary (M1 Slice 1, EG-M1-1)
test(egts): EGTS-M0 meta-tests + test-core/evidence + coverage (M0 Slice 10, EGTS-M0-7)
```

**Branch:** `<type>/<build>-slice<n>-<slug>`, where `<build>` is `evalglass-m0`…
`evalglass-m5`, `scan-gate`, or `validator-gate` — e.g. `feat/evalglass-m1-slice1-cli-config`.

**Body:** what changed and why, wrapped ≈72 cols. **No AI attribution** — never add
`Co-Authored-By` or "Generated with …"; the maintainer authors all commits and PRs.

## 23. Governing Per-Slice Workflow (the rule — follow to the end)

**Build in slices; one slice = one PR.** The slice sequence for a milestone is its
build-gate/slice table in the local `docs/IMPLEMENTATION_PLAN.md` working doc (e.g. Slice 0 = test harness +
repo-config, then the contracts/loader/detector/output slices in dependency order, then
a final acceptance slice). This is the most important implementation rule — follow every
step to the end, every slice; do not skip ahead.

Per-slice loop — repeat for every slice:

1. **Tests first.** Write the slice's failing tests + fixtures and confirm they fail
   (red). Enumerate the fail-closed / malformed / adversarial cases up front (Lesson 2).
   For a detector, write **both** a sensitivity (bad-diff that must fire) and a
   specificity (good-diff that must stay quiet) fixture.
2. **Build** until the slice's tests pass (green). Run them locally — GitHub CI does not
   run the skills' own suites, so this local Layer-1 run is the real gate (Lesson 4).
3. **Scan-gate** (`scan-gate`, debug mode) on the committed slice diff. Report issues;
   don't be blocked by it, but assess the output and fix what matters. Re-run the slice
   tests after fixes.
4. **Validator-gate** (`validator-gate`, debug mode). Report issues; assess and fix what
   matters. Re-run the slice tests after fixes.
5. **Review.** Run Codex review on the slice diff (`codex review --commit HEAD`, scoped to
   the committed slice — Lesson 5). Triage and fix what matters (not every nit). Re-run
   the slice tests after fixes.
6. **PR.** Push the branch (per §22) and open a PR to `main`.
7. **CI.** Check the GitHub CI checks; fix any failures and re-push until green. Never
   merge red CI.
8. **Merge.** Only when review is addressed and CI is green: squash-merge. Then start the
   next slice.

Hard rules: never skip tests-first; scope scan/validator/review to the committed diff;
isolated git worktree if a parallel agent shares the checkout, and verify the merged
commit actually contains the fixes (Lesson 3); a milestone is done only after its
EGTS-Mx proof suite is green, coverage shows it `covered`, and the validator-gate finds
no overclaim over the milestone evidence pack.
