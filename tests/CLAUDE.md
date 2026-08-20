# AGENTS.md - EvalGlass Test System

This is the canonical working guide for EGTS, the EvalGlass Test System.
Use `AGENTS_test_uncompressed.md` for the full v2 record.

EGTS proves EvalGlass. It does not become EvalGlass.

EvalGlass owns evaluation meaning: public contracts, score semantics,
diagnostics, provenance, authority, calibration, baselines, the Verdict Engine,
`RunRecord`, and `Scorecard`. EGTS owns proof: scenarios, fixtures, real product
runs, artifact checks, negative controls, coverage, and evidence.

## 1. Prime Directive

EGTS answers:

```text
Can real EvalGlass produce a green, passing, or non-failing result that a
maintainer could misread as more authoritative than the evidence permits?
```

If yes, either EvalGlass is incomplete or EGTS has not proved enough.
The answer must come from real product paths, typed product artifacts,
negative controls, coverage rows, and reviewable evidence.

A real proof has:

- a named product ticket or architecture promise;
- deterministic fixtures;
- a real EvalGlass public surface;
- typed product artifacts;
- checkers that compare declared expectations to product output;
- a negative control for the failure mode;
- coverage rows mapped to tickets and architecture promises;
- evidence readable without conversation memory.

## 2. Source Order

Read in this order:

1. `CLAUDE.md`
2. `test_jira_tickets.xlsx`
3. `test_architecture_build_contract.md`

If documents disagree, prefer the build contracts and current Jira workbooks,
then update AGENTS guidance.

## 3. Boundary

EGTS may:

- create disposable host projects and deterministic fixtures;
- invoke real EvalGlass core, CLI, skill, and optional-lane surfaces;
- collect `RunRecord`, `Scorecard`, reports, manifests, locks, baselines,
  ledgers, diffs, and sink outputs;
- compare typed artifacts to declared expectations;
- run seeded bad cases;
- emit coverage and evidence reports.

EGTS must not:

- compute EvalGlass verdicts;
- grant score authority;
- normalize scores for the product;
- approve thresholds, datasets, rubrics, calibration, or baselines;
- repair product artifacts before checking them;
- use report prose as the primary truth surface;
- require network, credentials, hosted trace backends, live models, Docker,
  daemons, vector stores, or optional lanes in required suites;
- let optional integrations become hidden required infrastructure.

## 4. Non-Negotiables

- Real product path: required scenarios invoke public EvalGlass surfaces.
- One Verdict Engine: EGTS checks product-emitted verdicts but never computes
  them.
- Typed artifacts first: `RunRecord` JSON and `Scorecard` JSON are primary.
- Hermetic required tier: required suites run locally and deterministically.
- Route fidelity: route scenarios use the route under proof.
- State isolation: workspaces, outputs, baselines, environment, and ledgers are
  fresh or explicitly declared.
- Negative controls: every critical checker family has seeded bad cases.
- Explicit coverage: product tickets and architecture promises map to scenario
  IDs.
- Optional means removable: optional lanes can be disabled or deleted without
  changing required-tier behavior.
- No hidden authority: green output must not imply unsupported approval,
  calibration, comparability, evidence quality, data safety, or provider trust.

## 5. Proof Workflow

Every proof should follow this path:

```text
Product obligation
  -> Coverage row
  -> Scenario metadata
  -> Deterministic fixture
  -> Real EvalGlass public surface
  -> Product artifacts
  -> Checker result
  -> Negative-control result
  -> Evidence report
```

Before editing, answer:

- Which product ticket or architecture promise is being proved?
- Which proof ring owns it?
- Which public surface must run?
- Which typed artifacts prove it?
- Which checker catches the overclaim?
- Which negative control proves that checker?
- Which coverage row shows the status?

## 6. Product Contracts

EGTS must prove these contracts without reimplementing their meaning:

- `TraceEnvelope`: vendor-neutral normalized behavior.
- `EvalUnit`: selected behavior slice.
- `Example`: evaluator-ready unit.
- `EvidenceBundle`: references, source evidence, judge evidence, verifier
  evidence, trace fragments, policy decisions, and runtime errors.
- `MetricSpec`: metric identity, applicability, thresholds, evidence needs,
  aggregation, and authority needs.
- `Score`: status, value, validity, diagnostics, provenance, authority.
- `RunRecord`: complete persisted run record.
- `Scorecard`: compact machine and human summary.
- Verdict Engine: only product path for `pass`, `fail`, `blocked`, and
  `informational`.
- `DatasetStore`, `TraceSource`, `TaskRunner`, `JudgeModel`, `ResultStore`,
  `ScoreSink`: effectful runtime ports, not meaning owners.
- `vendor-manifest.json`, `evalglass.lock`: skill installation identity and
  managed-file boundary.

## 7. Proof Rings

| Ring | Proves | Must not own |
| --- | --- | --- |
| Contract Proof | Contracts, serialization, evaluator protocol, score states, verdict rows. | Product semantics. |
| Route Proof | Dataset, trace, replay, judge, baseline, report, skill, sink, optional-lane paths. | Bypassing the route under proof. |
| Trust Proof | Authority, policy, threshold approval, judge calibration, drift, baseline comparability, report overclaim checks. | Human approval or domain truth. |
| Integration Proof | OpenTelemetry/OpenInference conformance, trace backends, `ScoreSink`, live judges, richer units. | Required dependency on external systems. |
| Evidence Governance | Coverage registry, Proof Planner, evidence reports, Negative Controls, deletion verification. | Product verdicts or product authority. |

Prefer one primary proof ring per scenario.

## 8. Repository Shape

Prefer this responsibility split:

```text
tests/egts/
  cli/
  suites/
    m0_core/
    m1_runtime/
    m2_trust_runtime/
    m3_skill/
    m4_judges/
    m5_extensions/
  scenarios/
  fixtures/
  coverage/
  checkers/
  negative_controls/
  proof_planner/
  evidence/
```

Installed host repositories may receive smoke tests under `evals/tests/`.
Those smoke tests are not the full EGTS suite.

## 9. Scenario Contract

Scenarios should be declarative. Checker code must not hide expectations that
belong in metadata.

Required fields:

- `id`
- `title`
- `milestone`: `EGTS-M0` through `EGTS-M5`
- `product_ticket`, for example `EG-M1-3`
- `egts_ticket` when available
- `proof_ring`
- `architecture_tags`
- `product_surface`
- `input_route`
- `fixture`
- `command`
- `expect.artifacts`
- `expect.verdict`
- `expect.exit_class`
- `expect.authority`
- `expect.diagnostics`
- `negative_control` when applicable
- `optional_lane` when not required-tier

Scenario quality checks:

- Can the product promise be named from the scenario alone?
- Would a broken route fail this scenario?
- Would an overclaiming report fail this scenario?
- Is the expected verdict declared, not computed by EGTS?
- Is the negative control tied to the same checker family?
- Is coverage precise enough for a reviewer?

## 10. Fixtures

Fixtures should be small, deterministic, and reviewable.

Use fixture families for:

- core contracts;
- disposable host projects;
- local JSONL datasets;
- local trace JSONL and OpenTelemetry/OpenInference-shaped traces;
- replay programs;
- fake judges, rubrics, calibration, threshold approvals, and drift;
- comparable and non-comparable baselines;
- skill fixture repositories;
- optional-lane samples;
- malformed negative-control cases.

Rules:

- Keep raw inputs separate from expected product artifacts.
- Do not hand-write product outputs except for checker mutation tests.
- Include stable fixture IDs in evidence.
- Use disposable result folders.
- Keep required-tier fixtures network-free.

## 11. Checkers

Checkers compare declared expectations to product artifacts. They do not
implement EvalGlass policy.

Required checker families:

- Contract checker: schema, serialization, stable enums, invalid states.
- Scorecard checker: verdict, authority, summaries, status counts, diagnostics,
  baseline state.
- RunRecord checker: config, examples, specs, scores, evidence refs, evaluator
  versions, provenance.
- Verdict checker: product-emitted verdict payload and reasons.
- Authority checker: proposed, approved, calibrated, drifted, policy,
  comparable, and non-comparable states.
- Trace checker: raw trace -> `TraceEnvelope` -> `EvalUnit` -> `Example`.
- Provenance checker: baseline and comparability fingerprints.
- Report checker: Markdown, terminal, and CI wording backed by `Scorecard`.
- Skill checker: diffs, `vendor-manifest.json`, `evalglass.lock`, scaffold.
- Sink checker: sink output is immutable scorecard rendering/export.
- Optional-lane checker: lane attaches through ports and can be removed.

Rules:

- Parse structured artifacts with structured parsers.
- Assert typed fields before rendered text.
- Avoid incidental timestamps, temp paths, and ordering.
- Error messages should name the violated contract.
- Every checker family needs a negative control.

## 12. Negative Controls

Negative controls prove EGTS can fail when EvalGlass overclaims or artifacts
drift.

Required patterns:

- mutated verdict payload;
- dropped evidence reference;
- blocked score encoded as zero;
- inflated authority;
- provider-native trace leaked to evaluator-visible fields;
- non-comparable baseline treated as regression proof;
- report says pass while `Scorecard` says blocked;
- skill overwrites host-owned truth;
- live judge used in required tier;
- `ScoreSink` mutates verdict or authority;
- optional lane deletion changes required output.

Ask for every critical proof:

```text
What bad artifact would make this checker fail for the right reason?
```

## 13. Commands

These commands, or documented equivalents, must exist:

| Command | Runs | Required-tier |
| --- | --- | --- |
| `egts test-core` | EGTS-M0 core proof. | Yes |
| `egts test-runtime` | EGTS-M1 runtime route proof. | Yes |
| `egts test-trust-runtime` | EGTS-M2 replay, baseline, policy, CI proof. | Yes |
| `egts test-skill` | EGTS-M3 skill and vendoring proof. | Yes |
| `egts test-judges` | EGTS-M4 fake judge and calibration proof. | Yes |
| `egts test-required` | Required suites for the current milestone. | Yes |
| `egts coverage` | Coverage completeness and missing obligations. | Yes |
| `egts evidence --target <id>` | Evidence for scenario, ticket, milestone, ring, or lane. | Yes for required targets |
| `egts test-lane <name>` | Optional live provider, trace backend, sink, annotation, synthetic, richer unit. | No |
| `egts verify-deletion` | Disable optional lanes and rerun required proof. | Yes |

Required commands must not make network calls, even if credentials are present.
Product `fail` and `blocked` can be successful tests when expected.

## 14. Coverage And Evidence

Coverage rows should include product ticket, EGTS milestone, product ring,
proof ring, architecture section, public contract or route, scenario IDs,
fixture family, checker family, negative-control ID, command, optional-lane
marker, evidence path, and status.

Allowed status values:

- `covered`
- `partial`
- `blocked`
- `optional`
- `not_started`

Evidence records should include scenario ID, ticket keys, fixture IDs, product
version or vendored identity, command result, artifact paths, checker results,
negative-control result, coverage status, blockers, skips, optional
prerequisites, and a short explanation of what was proved.

Rules:

- No scenario without coverage.
- No coverage row without scenario or explicit blocker.
- Evidence points to typed artifacts; it does not replace them.
- Product failure and test-system failure are distinct.
- Missing proof is named, not hidden.

## 15. Required And Optional Tiers

Required tier:

- local;
- deterministic;
- no network, credentials, hosted providers, live tracing systems, Docker,
  daemons, vector stores, or optional lanes;
- fake or local effectful edges where necessary;
- gates milestone acceptance.

Optional lanes:

- declare dependencies;
- skip clearly when prerequisites are absent;
- attach through product ports;
- preserve `RunRecord` and `Scorecard`;
- never run in required CI by default;
- include deletion verification;
- cannot change required-tier output.

Optional lanes increase integration confidence. They do not define whether the
local product works.

## 16. Milestone Proof

- EGTS-M0 Core Proof: contracts, score states, diagnostics, registry,
  evaluator protocol, aggregation, provenance, authority, baseline shape,
  Verdict Engine rows, serialization, effect-free core.
- EGTS-M1 Runtime Proof: CLI/config, `DatasetStore`, `TraceSource`, local
  datasets, local traces, OpenTelemetry/OpenInference conformance, route
  convergence, evaluator loading, `ResultStore`, local `ScoreSink`, reports.
- EGTS-M2 Trust Runtime Proof: `TaskRunner`, runtime error separation,
  comparable baselines, non-comparable baselines, CI exits, annotations, data
  policy, deterministic replay evidence.
- EGTS-M3 Skill Proof: discovery, install plan, managed files,
  `vendor-manifest.json`, `evalglass.lock`, scaffolded host-owned truth,
  re-vendoring, rollback, post-install runtime independence.
- EGTS-M4 Judge Proof: `JudgeModel`, fake judge evidence, rubric provenance,
  parser diagnostics, missing calibration, approved calibration, threshold
  approval, drift, optional live-lane boundary.
- EGTS-M5 Extension Proof: optional dependency policy, OpenTelemetry and
  OpenInference conformance, trace backend adapters, `ScoreSink` export lanes,
  richer `EvalUnit`, annotation, synthetic data, benchmarking governance,
  deletion verification.

## 17. Special Risk Areas

- Trace proof must show `raw trace -> TraceSource -> TraceEnvelope -> EvalUnit
  -> Example + EvidenceBundle -> core -> RunRecord + Scorecard`.
- Authority proof must show whether a claim is informational, proposed,
  approved, calibrated, drifted, policy-blocked, evidence-blocked, comparable,
  or non-comparable.
- Report proof checks typed artifacts first, then human wording.
- Skill proof separates managed framework files, `vendor-manifest.json`,
  `evalglass.lock`, and host-owned truth.
- Sink proof ensures `ScoreSink` lanes render or export immutable scorecard
  data.

## 18. Common Recipes

Add a scenario:

1. Identify product ticket or architecture promise.
2. Choose proof ring and route.
3. Add or reuse deterministic fixture.
4. Declare expected artifacts, verdict, exit class, authority, diagnostics, and
   command.
5. Wire checkers.
6. Add or link a negative control.
7. Update Coverage Registry.
8. Run the narrow command and inspect typed artifacts.

Add a checker:

1. Name the product artifact it reads.
2. Name the contract it proves.
3. Assert only product-emitted fields.
4. Add one passing scenario.
5. Add one seeded bad artifact or fixture.
6. Make failure output name the violated contract.
7. Register coverage.

Add optional-lane coverage:

1. Declare lane name and dependencies.
2. Keep required-tier imports clean.
3. Add local conformance or fake-backed proof where possible.
4. Add real integration scenario only when prerequisites exist.
5. Add deletion verification.
6. Mark coverage rows optional.

## 19. Reject

Reject changes that:

- duplicate the product Verdict Engine;
- compute score authority in EGTS;
- use Markdown as the only assertion surface;
- inject evaluator-ready objects when route fidelity is under proof;
- run required suites against live providers or hosted trace platforms;
- silently skip missing required coverage;
- let optional integrations mutate `RunRecord` or `Scorecard`;
- treat infrastructure failure as low score;
- treat judge parser failure as low score;
- treat non-comparable baselines as regression proof;
- overwrite host-owned truth during skill tests;
- remove negative controls because they are inconvenient;
- make proof unreadable without conversation context.

## 20. Definition Of Done

An EGTS change is complete when:

- real EvalGlass public surfaces are exercised;
- required-tier proof remains local and deterministic;
- typed artifacts are checked before rendered text;
- product verdict and authority come only from product output;
- route fidelity is preserved;
- negative controls prove checker sensitivity;
- Coverage Registry rows map product tickets and architecture obligations;
- evidence reports point to reviewable artifacts;
- optional lanes remain removable;
- docs and AGENTS guidance match the current architecture.

Final rule:

```text
EGTS is not done when tests exist.
EGTS is done when it proves real EvalGlass cannot quietly overclaim.
```
