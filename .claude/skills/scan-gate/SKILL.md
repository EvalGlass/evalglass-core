---
name: scan-gate
description: >-
  Diff-aware trust-policy scanner for the EvalGlass repo. Run it after an
  implementation step (or before opening a PR) to check the agent's changed code
  for EvalGlass-specific trust violations that generic CI cannot see: effects in
  the effect-free core, verdict-logic duplication outside the Verdict Engine,
  optional/vendor SDK leakage into required paths, generated-data-treated-as-
  authority, host-owned overwrites, secrets, and CI/shell verdict spoofing. Emits
  a normalized scan-gate.result.json (PASS / WARN / BLOCKED / FAIL). Use when
  checking a diff, as a pre-PR gate, or as the per-step gate in the Execution
  Loop. It scans and reports evidence; it never decides the final loop status.
---

# Scan Gate

A small, **diff-aware policy scanner** that catches the EvalGlass-specific *trust*
violations an implementing agent can introduce, and emits normalized evidence the
(future) Execution Loop Synthesizer can consume.

It is **not** EvalGlass, not the generic CI suite, and not the final decision. Generic
hygiene (ruff, mypy, bandit, pytest, secrets, CVEs, licenses) is already enforced by
GitHub CI; the Scan Gate adds the trust checks CI cannot see.

## Running a scan

```bash
python .claude/skills/scan-gate/scripts/scan_gate.py run \
  --repo . --base origin/main --head WORKTREE \
  --profile fast \
  --policy .claude/skills/scan-gate/policies/evalglass.fast.yml \
  --json .claude/skills/scan-gate/last-run/scan-gate.result.json \
  --markdown .claude/skills/scan-gate/last-run/scan-gate.summary.md
```

Exit codes: `PASS`/`WARN` → 0, `FAIL` → 1, `BLOCKED` → 2. `scan-gate.result.json` is
authoritative. Subcommands: `run` (scan), `diff` (emit the diff pack), `policy` (validate).

### Coverage (why a PASS is not always a trust check)

The trust detectors are **path-scoped**: `imports_effects`, `generated_authority`,
`ci_script_guard`, and `manifest_drift` only inspect files that match a product path group
(`src/evalglass/**`, `evals/**`, `.github/workflows/**`, `**/*.sh`, manifests, and the gate
skills' own Python under `.claude/skills/**/*.py`). A diff whose files match only the universal
`all` group (e.g. docs, JSON/schema artifacts, or a brand-new top-level package) is seen **only**
by the `secrets` sweep — every semantic trust detector short-circuits, so the scan returns `PASS`
with `findings: 0` *without having trust-checked that code*.

To keep that honest, `run` prints a coverage line to **stderr** whenever changed files fall
outside every path-scoped rule, and `--debug` prints a full per-file table:

```bash
python .claude/skills/scan-gate/scripts/scan_gate.py run ... --debug
# scan-gate: coverage — 5/5 changed file(s) matched only the universal group;
#   no path-scoped trust detector inspected them. A PASS here is NOT a trust check of that code.
```

The same signal is also written to the authoritative JSON (so a consumer that reads only
`scan-gate.result.json` and suppresses stderr still sees it): `summary.trust_scoped` /
`summary.not_trust_scoped` counts, and `environment.coverage_note` naming the un-checked files
when a blind spot exists. The per-file `--debug` table stays stderr-only. If you want new
locations actually trust-checked, add a path group + rule to the policy.

## Detectors (fast/required profiles)

path classifier · imports/effects (vendor & effects in core, optional-lane leakage,
verdict-logic duplication; reuses `tools/check_core_isolation.py`; **plus a network/provider-import
guard on the hermetic gate skills under `.claude/skills/**`**) · secrets · generated-
authority / host-owned guard · CI/script verdict-spoof guard · manifest drift (warn).

## Statuses (the vocabulary)

- `PASS` — the selected checks ran and found no blocking issue.
- `WARN` — only non-blocking findings (e.g. manifest drift flagged for review).
- `BLOCKED` — a required check could not run honestly (unclassifiable high-risk path,
  missing base ref, tool failure/malformed output, invalid policy). **Never a silent pass.**
- `FAIL` — a concrete policy violation.

`scan-gate.result.json` is the authoritative output; Markdown is a rendering of it.

## Running the test suite

The skill's own tests are self-contained and run offline:

```bash
python -m pytest -c .claude/skills/scan-gate/pytest.ini .claude/skills/scan-gate/tests
```

## Boundaries

- Scans only the **changed** files/lines of a diff — fast, low-noise.
- Reuses the repo's `tools/check_core_isolation.py` for core-effect detection.
- Defers generic CVE/type/style/test coverage to GitHub CI.
- Emits evidence; the Synthesizer (not the Scan Gate) decides the final loop status.
