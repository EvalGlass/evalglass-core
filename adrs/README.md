# Architecture Decision Records

EvalGlass uses ADRs to record decisions that are **public-facing** or **hard to reverse** — per CLAUDE.md §8, every dependency is "vendored cost," and any change to architecture boundaries, public contracts, or gating behavior should leave a paper trail.

## When to write an ADR

- Adding a runtime dependency.
- Changing a public API, CLI contract, or report schema.
- Changing what the Verdict Engine emits or how authority states map to verdicts.
- Adding or removing a port; introducing a new adapter family.
- Changing the host-repo layout the skill scaffolds.
- Adopting or replacing a tool that touches the build / test / release pipeline.

If you are unsure, err on the side of writing one. ADRs are cheap.

## Process

1. Open an `adr:` issue using the template at `.github/ISSUE_TEMPLATE/adr_proposal.yml`.
2. Discuss until rough consensus.
3. Open a PR adding `adrs/NNNN-slug.md` (next sequential number).
4. PR review uses the standard CODEOWNERS workflow.

## Format

Keep ADRs short. Use the headings: **Context**, **Decision**, **Status** (`proposed | accepted | superseded by NNNN`), **Consequences**.

## A note on "Source:" provenance

Some ADRs carry a **Source:** line naming the planning artifact the decision was derived from — a milestone plan (e.g. `docs/IMPLEMENTATION_PLAN.md`, `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md`, `docs/PLUGIN_TRANSFORMATION_PLAN.md`, `docs/PRODUCT_ARCHITECTURE_TEST_PLAN.md`) or a Jira workbook (`*_jira_tickets*.xlsx`). Those artifacts are **kept locally and no longer committed** — they add noise to every clone — so a fresh checkout will not contain them, and that is expected. A "Source:" line is *historical provenance*: it records what informed the decision at the time, not a file you need in order to read the ADR. The durable record is the ADR itself, plus `CHANGELOG.md` for what shipped.

## Existing ADRs

- [0001 — Architecture boundary (Core / Harness / Skill)](0001-architecture-boundary.md)
- [0002 — Package manager: uv](0002-package-manager-uv.md)
- [0003 — Linter and formatter: ruff + mypy strict](0003-linter-ruff-mypy.md)
- [0004 — SonarCloud as informational quality signal](0004-sonarcloud-informational.md)
- [0005 — Runtime Harness CLI and config boundary: argparse + PyYAML](0005-harness-cli-and-config.md)
- [0006 — Open-convention (OpenTelemetry / OpenInference) trace mapping subset](0006-open-convention-trace-mapping.md)
- [0007 — Subprocess TaskRunner contract](0007-subprocess-taskrunner.md)
- [0008 — CI annotations and the exit-class taxonomy](0008-ci-annotations-exit-class.md)
- [0009 — Baseline file format and explicit promotion](0009-baseline-file-and-promotion.md)
- [0010 — EvalGlass Skill home and shape](0010-skill-home-and-shape.md)
- [0011 — Vendoring namespace and runtime invocation](0011-vendoring-namespace.md)
- [0012 — vendor-manifest.json and evalglass.lock formats](0012-vendor-manifest-and-lock.md)
- [0013 — Host discovery depth](0013-discovery-depth.md)
- [0014 — JudgeModel port and the fake-adapter contract](0014-judge-model-port.md)
- [0015 — Judge evidence, calibration, and threshold-approval record formats](0015-judge-evidence-and-calibration.md)
- [0016 — Optional live judge provider lane](0016-optional-live-judge-lane.md)
- [0017 — Extension-lane framework and optional-dependency policy](0017-extension-lane-framework.md)
- [0018 — Trace backend adapter contract (stub-first)](0018-trace-backend-adapter.md)
- [0019 — ScoreSink export lane contract](0019-score-sink-export-lane.md)
- [0020 — Richer EvalUnit model (step / trajectory / session)](0020-richer-evalunit.md)
- [0021 — Generated-evidence governance (annotation / synthetic / benchmark)](0021-generated-evidence-governance.md)
- [0022 — Claude Code plugin packaging and delivery boundary](0022-plugin-packaging-and-delivery.md)
- [0023 — Codex second-runtime packaging](0023-codex-second-runtime-packaging.md)
- [0024 — Score subject identity (additive provenance)](0024-score-subject-identity.md)
- [0025 — Authoring tier and advanced extensions (v1.1)](0025-authoring-tier-and-advanced-extensions.md)
- [0026 — Rename the integration-time package `skill` → `installer`](0026-rename-skill-package-to-installer.md)
- [0027 — Marketplace named after the publisher (superseded by 0062)](0027-marketplace-named-after-publisher.md)
- [0028 — `authority.json` is a host-owned ledger; the runtime never reads it](0028-authority-json-is-ledger-only.md)
- [0029 — Frozen public-surface snapshots and the capability-status taxonomy](0029-frozen-spine-snapshots-and-capability-status.md)
- [0030 — Companion-ontology drift guard (vendored artifact, two tracks)](0030-companion-ontology-drift-guard.md)
- [0031 — Runner-attach seam, `lanes:` config, and the `RunRecord.lane_results` side channel](0031-runner-attach-seam-and-lane-results.md)
- [0032 — Companion-ontology reconciliation: edit the vendored copy, strict Track B, deferred source sync](0032-ontology-reconciliation-workflow.md)
- [0033 — Live trace-connector boundary and optional provider-SDK policy](0033-live-trace-connector-boundary.md)
- [0034 — Langfuse trace connector](0034-langfuse-trace-connector.md)
- [0035 — Phoenix trace connector](0035-phoenix-trace-connector.md)
- [0036 — LangSmith trace connector](0036-langsmith-trace-connector.md)
- [0037 — Per-source-function score view is not built (M6 never-build)](0037-per-source-function-view-not-built.md)
- [0038 — M7 "Epistemic Core": level up alpha's measurement without shedding its breadth](0038-m7-epistemic-core-tranche.md)
- 0039 — *retired: automated metric discovery is out of scope for the core (metrics are host-authored).*
- [0040 — Generic OpenAI-compatible judge lane](0040-openai-compatible-judge-lane.md)
- 0041 — *retired: no automated discovery scaffolder ships in the core (metrics are host-authored).*
- [0042 — Host command judge (subprocess JudgeModel)](0042-host-command-judge.md)
- [0043 — HTML Scorecard report (dashboard + deltas)](0043-html-scorecard-report.md)
- [0044 — Interval bounds are rounded to a platform-independent precision](0044-portable-interval-floats.md)
- [0045 — Config-reachable trajectory / session unit ladder](0045-config-reachable-unit-ladder.md)
- [0046 — `connect --live` verb over the shipped connector lanes](0046-connect-live-verb.md)
- [0047 — Diagnostic clusters in the Scorecard](0047-diagnostic-clusters.md)
- [0048 — Continuous drift watcher](0048-drift-watcher.md)
- [0049 — Per-metric example selectors (`applies_to`)](0049-per-metric-example-selectors.md)
- [0050 — EvaluationPlan as a persisted, plan-before-effects execution contract](0050-evaluation-plan-execution-contract.md)
- [0051 — Connected-evidence contracts: import manifests, behavior layers, assembly, references](0051-connected-evidence-contracts.md)
- [0052 — OpenAI-compatible judge as a first-class config adapter](0052-openai-compatible-judge-config-adapter.md)
- [0053 — Structured rubric contract and structured judge-result](0053-structured-rubric-and-judge-result.md)
- [0054 — Persist complete judge evidence in the RunRecord](0054-persist-complete-judge-evidence.md)
- [0055 — Judge execution policy: cache, budgets, and bounded retry](0055-judge-execution-policy.md)
- [0056 — Explicit metric source and evidence bindings](0056-metric-source-bindings.md)
- [0057 — Resolve authority from each metric's consumed evidence](0057-metric-scoped-authority.md)
- [0058 — First-class per-metric population accounting](0058-population-accounting.md)
- [0059 — Persist the typed paired comparison as primary truth](0059-primary-paired-comparison.md)
- [0060 — Diagnostic dashboard projection and default HTML renderer](0060-dashboard-projection-and-renderer.md)
- [0061 — Immutable run-series index and honest descriptive progression](0061-run-series-index.md)
- [0062 — EvalGlass owns its identity: marketplace `evalglass`, plugin `evalglass-core`](0062-evalglass-owns-its-identity.md)
