# EvalGlass Test Environment - Design Principles

**Status:** Design principles v2  
**Date:** 2026-05-27  
**Scope:** Principles for the EvalGlass Testing System (EGTS) test
environment: specimen hosts, fixtures, scenarios, evidence packs, optional
lanes, and the controlled worlds used to prove EvalGlass.  
**Not scope:** Product implementation details for EvalGlass itself, concrete
scenario files, fixture data, command implementation, or testkit code.

This document refreshes the original "test environment" principles to match the
current EvalGlass and EGTS architecture. The original core idea remains right:
to test EvalGlass, we do not need a good AI product; we need controlled worlds
where host behavior, authority, provenance, calibration, policy, and baselines
are known.

The central rule is no false confidence:

> A green or non-failing EGTS result must never let a maintainer believe
> EvalGlass has more evidence, authority, comparability, calibration, or safety
> than it actually has.

## 0. Source Of Truth

Read current sources in this order before changing test-environment design:

1. `../CLAUDE.md` — the product operating guide (with `../AGENTS.md`, the Codex
   entry point).
2. `../tests/CLAUDE.md` — the EGTS working guide.
3. `../tests/test_architecture_build_contract.md` — the EGTS build contract.
4. `design_principles.md` — the product design principles.
5. `architecture.md` and `architecture_build_contract.md` — the product
   implementation architecture and build contract.
6. `../adrs/` — the architecture decision records for public-facing or
   hard-to-reverse choices.

Treat older draft docs, stale Atlassian tickets, old backlog files, and
conversation memory as background only. Current vocabulary is:

- EGTS, not generic "test environment" when naming the system.
- Evaluation Core, not kernel.
- Runtime Harness, not runner when referring to product architecture.
- Verdict Engine, not test-side decision logic.
- `pass`, `fail`, `blocked`, and `informational`.
- RunRecord JSON and Scorecard JSON before report prose.
- Required Tier and Optional Lane.

## 1. What This Document Is

This document defines principles for designing the controlled test environment
inside EGTS. It explains what kinds of specimens, fixtures, scenarios, and
evidence must exist so EGTS can prove EvalGlass honestly.

It does not define:

- the product architecture;
- concrete scenario schema fields;
- exact repository layout;
- implementation tickets;
- code-level testkit APIs;
- final command names.

Those are owned by the EGTS build contract, product build contract, Jira
workbooks, and AGENTS files.

## 2. The Inversion Principle

In normal EvalGlass use, the host AI system is unknown and EvalGlass reports
the measurement.

In EGTS, this is inverted:

- Host/specimen behavior is controlled input.
- EvalGlass is the subject under test.
- EGTS checks whether real EvalGlass emits the honest output.

The specimen's job is to be measured, not improved. If the test environment
starts tuning the specimen to make EvalGlass green, it is testing the wrong
thing.

## 3. Inner Loop And Outer Loop

Keep the two loops separate.

| Loop | Subject | Truth Source | Passing Means |
|---|---|---|---|
| Inner loop | Host specimen | Scenario mode, datasets, traces, rubrics, baselines | The specimen produced the configured behavior. |
| Outer loop | EvalGlass | Authored expected verdict, exit class, authority, provenance, diagnostics | Real EvalGlass reported the honest result. |

A host reference answer is not an expected EvalGlass verdict. A scenario
expecting EvalGlass to return `fail`, `blocked`, or `informational` passes when
that is the honest product output.

Every scenario should make this separation explicit. Host gold, rubrics, and
specimen mode belong to the controlled world. Expected Scorecard fields,
verdict, exit class, authority claim, provenance claim, diagnostics, ledgers,
and diffs belong to the EGTS assertion.

## 4. The Specimen Is A Controlled Oracle

The specimen host should be the simplest host-like system that can trigger real
EvalGlass behavior.

It should be:

- deterministic by default;
- configurable by mode, not by real model behavior;
- better at producing controlled failures than polished successes;
- able to emit good, bad, malformed, missing, timed-out, drifted, and
  policy-sensitive behavior;
- able to produce dataset outputs, trace-like outputs, subprocess outputs, and
  controlled file effects;
- replaceable by static fixtures when the route under test does not require a
  live specimen process.

The required tier uses deterministic specimens and authored evidence. Real
models, hosted backends, containers, durable workflows, and external services
belong only to optional lanes.

## 5. Real EvalGlass Must Be Under Test

The test environment surrounds EvalGlass. It must not replace EvalGlass.

EGTS may create:

- scenarios;
- fixture workspaces;
- datasets and traces;
- fake effect adapters;
- call ledgers;
- authority/calibration/baseline records;
- expected product artifact assertions;
- evidence packs.

EGTS must not create:

- a second Evaluation Core;
- a second Runtime Harness decision path;
- a second Verdict Engine;
- a second authority policy;
- test-only CI exit mapping;
- report-only truth;
- product semantics hidden in checkers.

Checkers compare authored expectations against real EvalGlass outputs. They do
not compute verdicts, authority, or baseline comparability.

## 6. Test The Architecture Seams

The controlled environment exists to put pressure on EvalGlass's hard seams.
Each seam needs dedicated scenarios.

| Seam | What EGTS Must Prove |
|---|---|
| Evaluation Core vs Runtime Harness | Core stays effect-free; runtime effects do not leak into meaning. |
| Verdict Engine chokepoint | Only the product Verdict Engine emits `pass`, `fail`, `blocked`, or `informational`. |
| Route convergence | Dataset replay, trace import, subprocess replay, direct core fixtures, and CLI paths converge through `TraceEnvelope -> EvalUnit -> Example`. |
| JSON before prose | Scorecard JSON, RunRecord JSON, and typed diagnostics are asserted before Markdown. |
| Skill vs runtime | The vendored runtime works after the skill and coding-agent context are removed. |
| Managed vs host-owned files | Re-vendoring preserves host-owned truth and records managed-file patches. |
| Optional lane deletion | Removing optional lanes leaves the required tier green. |

The environment should include adversarial fixtures that tempt these seams to
collapse, such as Example-shaped traces, report wording that could overclaim,
or ScoreSink failures that must not alter the core verdict.

## 7. Verdict Matrix Is The Spine

EGTS must be able to drive controlled input and controlled authority into every
verdict row.

| Configuration | Required EvalGlass Verdict | CI Meaning |
|---|---|---|
| No metric has gating authority. | `informational` | Exit zero; report states no active gate. |
| All active gates are valid, authorized, comparable where required, and above approved thresholds. | `pass` | Exit zero. |
| An active gate is validly measured and below an approved threshold. | `fail` | Nonzero; report names metric, score, threshold, diagnostic cause. |
| An active gate is blocked, errored, non-evaluable, policy-forbidden, missing evidence, or missing required comparable baseline. | `blocked` | Nonzero; report explains EvalGlass cannot make an honest quality claim. |
| Reference metric uses proposed or retired data. | `informational` unless another gate fails or blocks. | No hidden authority. |
| Judge metric lacks calibrated authority. | `informational` unless another gate fails or blocks. | No hidden authority. |

`fail` and `blocked` are different truths. Both may exit nonzero, but they must
be asserted as different verdicts with different explanations.

## 8. Authority Is A Dial Independent Of Quality

The environment must control authority independently from specimen quality.

Required authority axes:

- dataset status: proposed, validated, retired;
- metric status: draft, informational, calibrating, gating, retired;
- threshold status: proposed, approved;
- judge calibration: uncalibrated, calibrating, calibrated, drifted, retired;
- data policy: permitted, redacted, forbidden, missing policy, unknown;
- baseline state: comparable, not comparable, missing, not requested.

Required adversarial combinations:

- good specimen with no authority -> `informational`, not `pass`;
- bad specimen with no authority -> `informational`, not `fail`;
- bad specimen with full authority -> `fail`;
- active gate that cannot honestly run -> `blocked`;
- generated gold or generated thresholds -> informational until validated and
  approved;
- non-comparable baseline -> blocked or informational by policy, never a
  regression proof.

Authority records are fixture data. Authority decisions are product output.

## 9. Fake-First Effects

Required-tier fakes are not fake EvalGlass. They are controlled effect edges.

Allowed required-tier fakes:

- fake judge evidence;
- fake verifier/RAG evidence;
- fake provider call ledgers;
- fake trace sources;
- fake subprocess specimen programs;
- fake clocks only where injected into EGTS fixtures, not product core;
- fake external services behind public ports.

Rules:

- fakes bind through public Runtime Harness ports;
- fakes write ledgers;
- fakes return evidence, not verdicts;
- fake failures are first-class fixture states;
- live providers and real backends are optional lanes only.

Malformed fake judge output, missing verifier evidence, policy-forbidden calls,
and drifted calibration are required honesty cases. They must become typed
diagnostics, blocked states, or informational states according to product
policy, not silent passes.

## 10. Baselines Need Time And Comparability

Regression proof requires pairs of runs and structured comparability.

The environment must produce:

- clean baseline run;
- candidate run with comparable fingerprint;
- candidate run with changed dataset, metric, evaluator, config, rubric, policy,
  or specimen version;
- missing-baseline case;
- same-looking score numbers with non-comparable fingerprint.

Score deltas are not proof by themselves. EGTS must assert the product
baseline/comparability claim from Scorecard or RunRecord JSON.

## 11. Data Policy Must Be Exercised

Data policy controls what evidence may be used and where effects may route. The
environment must include scenarios where a metric wants a forbidden route.

EGTS must prove:

- forbidden egress paths are not called;
- the call ledger shows the absence of forbidden calls;
- policy-forbidden active gates become `blocked`, not low scores;
- redaction and missing-policy cases are visible;
- reports explain policy decisions from typed Scorecard data.

The strictest local/no-egress setting is just a policy state. It should not
force a separate architecture.

## 12. Verifier, RAG, And External Evidence

Verifier and RAG evidence are in scope as controlled evidence paths, but they
must not become hidden gates.

Principles:

- required tier uses fake verifier/RAG evidence only;
- verifier-backed metrics remain informational until authority is typed and
  approved;
- default-disabled verifier paths degrade honestly;
- missing or malformed external evidence becomes diagnostics;
- external evidence may inform a metric but never override EvalGlass authority;
- live verifier, vector store, or RAG backend checks belong to optional lanes.

Treat every new port or extension as a possible authority-smuggling path and
test it accordingly.

## 13. Stage Order

EGTS should be built in the current T0-T7 order, not the older M0-M5-only test
environment order.

| Stage | Environment Design Focus |
|---|---|
| T0 | Scenario schema, command surface, evidence pack shape, coverage ledger, hermetic guardrails. |
| T1 | Direct real core contract scenarios, public JSON snapshots, verdict matrix, core isolation. |
| T2 | Isolated workspaces, scenario runner, route convergence, structured checkers. |
| T3 | Deterministic specimen programs, required adapter fakes, call ledgers, fixture factories. |
| T4 | Authority, calibration, baselines, provenance, data policy, false-confidence refusals. |
| T5 | Runtime CLI, Scorecard JSON, RunRecord JSON, reports, CI exits, required-tier composition. |
| T6 | Skill install, safe defaults, vendoring, re-vendoring, host-owned preservation, runtime independence. |
| T7 | Optional lanes, live providers, real backends, RAG, async/trajectory, deletion verification. |

A stage must not depend on future-stage machinery unless explicitly marked as
an optional lane. Do not advance a stage by weakening earlier guarantees.

## 14. Scenario And Evidence Principles

Every scenario should declare:

- stable id and coverage tags;
- public product contract under proof;
- input route;
- fixture set;
- specimen behavior;
- authority/calibration/baseline/policy records;
- expected Scorecard fields;
- expected verdict;
- expected exit class;
- expected provenance and diagnostics;
- expected reports, ledgers, evidence files, or diffs.

Every meaningful run should produce an evidence pack with:

- scenario id and coverage mapping;
- invocation metadata;
- scenario config snapshot;
- Scorecard JSON and RunRecord JSON;
- diagnostics and report output;
- adapter ledgers;
- file diffs;
- baseline/provenance/authority records;
- optional-lane status and blockers.

Evidence should make failures reproducible without relying on conversation
memory.

## 15. Meta-Properties Of The Environment

The test environment itself must be trustworthy.

Required properties:

- deterministic by default;
- scenario-local state;
- no shared baselines or calibration unless explicitly fixture-scoped;
- no ambient credentials;
- no network in required tier;
- no optional lane dependencies in required imports;
- no silent scenario skipping;
- no missing expected verdicts;
- readable failure messages naming the violated contract;
- deletion-friendly optional lanes;
- stable JSON ordering for snapshots and evidence.

Seeded-bad meta-tests are valuable. EGTS should be able to prove that missing
expectations, forbidden imports, hidden network use, duplicate verdict logic, or
lost provenance would fail the test system.

## 16. Explicit Non-Goals

The test environment must not become:

- a real product;
- a benchmark of record;
- a leaderboard;
- a model optimizer;
- a hosted backend;
- a second EvalGlass;
- a second Verdict Engine;
- a substitute for domain judgment;
- a suite that requires live models or network access in the required tier.

It also must not tune the specimen to pass. The specimen is controlled input,
not a target for improvement.

## 17. Definition Of Done

The test-environment design is sufficient only when EGTS can answer yes to all
of these:

1. Can it drive real EvalGlass into every verdict row and assert verdict, exit
   class, authority, diagnostics, and report clarity?
2. Can it prove a fresh skill install is informational until human validation
   confers authority?
3. Can it distinguish `fail` from `blocked` beyond process exit code?
4. Can it prove the Evaluation Core stays effect-free?
5. Can it prove only product Verdict Engine output controls CI meaning?
6. Can it grant, revoke, and drift authority inputs and observe product
   responses?
7. Can it stage comparable and non-comparable baselines?
8. Can it run vendored runtime after skill and agent context are removed?
9. Can it enable and delete every optional lane while required tier stays green?
10. Can it stage false-confidence traps and prove EvalGlass refuses them?

If any answer is no, the design is not finished.

Final question:

```text
Could a green EGTS result let someone believe EvalGlass proved more than its
typed evidence, authority, calibration, provenance, or baseline comparability
supports?
```

If yes, the test environment is not finished.
