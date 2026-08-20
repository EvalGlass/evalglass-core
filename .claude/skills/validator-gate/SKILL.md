---
name: validator-gate
description: >-
  Semantic trust gate for the EvalGlass Execution Loop (work in progress). Given
  an evidence pack of typed artifacts and one or more selected claims, it
  validates whether current evidence proves each claim WITHOUT crossing
  authority boundaries — catching overclaim that survives green tests, scans,
  and code review (duplicate verdict authority, reports/CI overclaiming beyond
  product evidence, regression claims without comparable baselines, EGTS
  checkers encoding product meaning, generated artifacts gone canonical,
  optional integrations gone required). Emits one validator.result.json
  (PASS / PASS_WITH_WARNINGS / BLOCKED / FAIL). It consumes Scan Gate and Code
  Review output as evidence; it never reimplements them, and the Execution Loop
  owns the final decision.
---

# Validator Gate

The Validator Gate is the **semantic** trust gate for the Execution Loop. It
validates whether current *typed evidence* proves a selected EvalGlass/EGTS
claim **without crossing authority boundaries**. It is **not** a gate selector,
scanner, code reviewer, test runner, release manager, or a second EvalGlass
Verdict Engine.

It reads an **evidence pack** (typed JSON artifacts + a declared source boundary
+ selected claims), routes each claim to the smallest necessary set of the five
canonical families, and returns exactly one `validator.result.json`. The
Execution Loop owns `decision_record.json`.

## Canonical families (closed set)

`contract_boundary` · `authority_verdict` · `evidence_provenance` ·
`scenario_checker` · `integration_boundary`. Risk-catalog references are
optional supporting metadata; they can never be family ids.

## Statuses

- `PASS` — selected claims are sufficiently proven by current evidence.
- `PASS_WITH_WARNINGS` — remaining uncertainty is explicit and non-critical.
- `BLOCKED` — required proof is missing, stale, contradictory, or outside the
  declared source boundary. **Never a silent pass.**
- `FAIL` — current evidence proves a semantic violation.

Precedence: `FAIL > BLOCKED > PASS_WITH_WARNINGS > PASS`. Trust-critical missing
proof is never downgraded to a warning.

## Running the gate

Give it an evidence pack (typed artifacts + source boundary + selected claims)
and it emits one `validator.result.json`:

```bash
python .claude/skills/validator-gate/scripts/validator.py run \
  --evidence-pack <pack>.json \
  --json   .claude/skills/validator-gate/last-run/validator.result.json \
  --markdown .claude/skills/validator-gate/last-run/validator.summary.md
```

Exit codes: `PASS`/`PASS_WITH_WARNINGS` → 0, `FAIL` → 1, `BLOCKED` → 2.
`validator.result.json` is the **authoritative** output; Markdown is a rendering
of it. Add `--debug` to print a non-authoritative trace to **stderr** — how each
claim routed and why, which family inspected which claim with which evidence, and
how the index classified the evidence (incl. artifacts materialized from adjacent
gates). It never changes the status, exit code, or JSON. `validate-evidence`
preflights a pack's structural usability without running families. The Execution Loop calls `scripts/adapter.py:run_adapter`,
which materializes Scan Gate / Code Review results as evidence and returns the
same result; the loop owns the final `decision_record`. See `runbook.md` for
when to run the gate and how to read each status.

## Running the test suite

The skill's tests are self-contained and run offline:

```bash
python -m pytest -c .claude/skills/validator-gate/pytest.ini .claude/skills/validator-gate/tests
```

GitHub CI does not run this suite; the local run is the skill's Layer-1 gate.
