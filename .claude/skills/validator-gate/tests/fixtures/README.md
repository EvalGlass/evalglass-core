# Validator Gate fixtures

Small, deterministic, reviewable evidence-pack fixtures. Raw inputs are kept
separate from expected product outputs. No fixture depends on a machine-local
absolute path, and the required tier runs offline.

## Layout

- `evidence_packs/clean.json` — the reference pack (a consistent
  `authority_verdict` claim). The skill smoke and runbook examples use it; it
  validates against `validator.evidence.v1` and yields `PASS`.
- `golden/<case>.pack.json` + `golden/<case>.result.json` — replayable golden
  pairs for the four outcomes (`pass`, `pww`, `blocked`, `fail`). Replay
  (`test_replay_golden.py`) reproduces each `*.result.json` exactly. The result
  carries no timestamps or absolute paths, so byte-equality is the regression
  guard. To intentionally evolve a contract, regenerate the `*.result.json`
  files and review the diff.

## Seeded bad cases

The seeded semantic bad-case matrix (`test_seeded_bad_cases.py`) is built inline
rather than as files: each case is a minimal evidence pack that trips exactly one
family's headline violation, run through the real `run_adapter` path, asserting
the expected family id + expected status. See that file for the 13-case matrix
mapping each violation to its family and status.

## Mapping to contracts

Every pack is a `validator.evidence.v1` document; every golden result is a
`validator.result.v1` document. The schema↔code consistency tests in
`test_contracts.py` keep those schemas pinned to the code enums and required
fields. Negative contract fixtures (bad enums, wrong-typed collection fields,
malformed adjacent-gate payloads) live in `test_contracts.py` and
`test_acceptance.py`.
