# EGTS — EvalGlass Testing System

EGTS is the **Layer-2 proof system** for EvalGlass. It answers one question
(`tests/CLAUDE.md §1`):

> Can EvalGlass produce a green/non-failing result a maintainer could misread as
> more authoritative than the evidence permits?

It drives **real product public surfaces**, compares typed artifacts
(`RunRecord`/`Scorecard` JSON) to **declared** scenario expectations, runs
**negative controls**, and emits coverage + evidence. EGTS never computes a
verdict, grants authority, or normalizes scores — it proves EvalGlass, it does
not become it.

EGTS is distinct from the fast **Layer-1** unit tests under `tests/{core,...}`,
which are white-box per-module and drive the red→green slice loop. EGTS is
black-box, anti-overclaim, and gates **milestone acceptance**.

## Layout (target — populated per milestone, not all at once)

```text
tests/egts/
  cli/                 # the `egts` command surface (test-core, coverage, evidence, ...)
  suites/              # pytest entrypoints per milestone (m0_core, m1_runtime, ...)
  scenarios/           # declarative scenario files (m0/, m1/, ...) — declared expectations
  fixtures/            # deterministic inputs (datasets, traces, baselines, rubrics, specimens)
  coverage/            # product_contracts.yaml, jira_ticket_map.yaml, ... -> scenario IDs
  checkers/            # contract, scorecard, runrecord, trace, authority, provenance, exit, ...
  negative_controls/   # seeded-bad fixtures that must fail for the right reason
  proof_planner/       # static obligation selection per ticket/milestone/contract/lane
  evidence/            # reviewable evidence reports (generated run outputs are gitignored)
```

Build order is lockstep with the product: EGTS-M0 proves EG-M0, etc. The harness
(scenario schema, coverage registry, `egts` CLI) is bootstrapped first
(Slices 1–2), then proof scenarios land as the real surfaces appear.

See `tests/CLAUDE.md` and the testing-system build contract for the full
scenario/checker/coverage contracts.
