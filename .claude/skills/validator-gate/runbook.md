# Validator Gate runbook

The Validator Gate answers one question for the Execution Loop:

> Does current typed evidence prove the selected EvalGlass/EGTS claim **without
> crossing authority boundaries**?

It reads an evidence pack and emits one `validator.result.json`. It never decides
the loop outcome — the Execution Loop folds this result into `decision_record`.

## When to run it

Run the Validator when a checkpoint asserts or changes semantic trust:

- verdict-engine behavior, score status, thresholds, confidence, calibration,
  judge influence;
- a public API / report / CI / dashboard / tracing / export contract;
- a provenance, baseline, regression, deletion, retention, or reproducibility
  claim;
- an EGTS scenario / fixture / checker / required-suite expectation;
- generated/proposed artifact authority, vendoring, an optional lane, a runtime
  route, RAG/data policy, or an external integration.

**Do not** run it for purely mechanical changes already covered by the Scan Gate
or ordinary code review. The router declines to validate a claim it cannot route
(it returns `BLOCKED`, not a guess).

## Reading the result

`validator.result.json` is authoritative. The overall `status` is the worst of
its family findings under the precedence **FAIL > BLOCKED > PASS_WITH_WARNINGS > PASS**:

| Status | Meaning | What to do |
| --- | --- | --- |
| `PASS` | Selected claims are sufficiently proven by current evidence. | Proceed; the gate adds no objection. |
| `PASS_WITH_WARNINGS` | Proven, but with explicit non-critical uncertainty (`warnings`). | Proceed; note the warnings. |
| `BLOCKED` | Required proof is missing, stale, contradictory, malformed, or outside the declared source boundary. | Supply the evidence named in `blocked_on`, then re-run. **Not** a soft pass. |
| `FAIL` | Current evidence proves a semantic violation. | Fix the violation in `findings[].reason`; `remediation` says how. |

Each `findings[]` entry names the `family_id`, the `claim_id`, the `status`, the
`evidence_refs` it inspected, a `reason`, a `remediation`, and an optional
`risk_ref`. `families_run`, `claims_validated`, `evidence_used`, `blocked_on`,
`warnings`, and `risk_references_used` summarize the run.

Trust-critical missing proof is always `BLOCKED`, never a `warning`. A `PASS`
means *these claims, given this evidence* — never a blanket guarantee.

## Examples

A clean pack (`tests/fixtures/evidence_packs/clean.json`) — a report whose
`claimed_status` matches the product verdict — yields `PASS`. Flip the report to
claim more than the product verdict and the `authority_verdict` family returns
`FAIL` (overclaim). Require an artifact the pack does not contain and the run is
`BLOCKED` with that artifact named in `blocked_on`.

## What it is not

Not a gate selector, scanner, code reviewer, test runner, release manager, or a
second Verdict Engine. It consumes Scan Gate and Code Review output as evidence;
it never reimplements them.
