# ADR 0009 — Baseline file format and explicit promotion

- **Status:** accepted
- **Date:** 2026-05-31

## Context

A regression claim is only honest when the current and baseline runs are
*comparable* on the dimensions that matter (build contract §10; `CLAUDE.md §11`).
The core already models this (`ComparableRunFingerprint`, `BaselineState`,
`RunFingerprint`); M2 must (a) define what a baseline file is, (b) load it and
feed it to the core, and (c) decide how a baseline is created. Two false-confidence
risks: a baseline that silently disappears (treated as "no baseline" and the gate
quietly downgraded), and a baseline created automatically by an ordinary run
(self-fulfilling "no regression").

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Baseline file | A promoted **`RunRecord`** JSON (the same artifact the result store writes) | No new schema to validate; it already carries the provenance fingerprint, scorecard, and scores. |
| Load | `harness/baseline.py:load_baseline(path) -> RunFingerprint` returns `RunRecord.from_dict(...).provenance` | Only the fingerprint is needed for comparability; the rest is human-reviewable context. |
| Load failure | missing / unreadable / malformed / not-a-RunRecord → **`SetupError`** (`baseline_not_found` / `baseline_unreadable` / `baseline_invalid`), exit 2 | A configured-but-unloadable baseline never silently becomes "no baseline" — that would let a required-baseline gate quietly pass. |
| Comparability | computed by the **core** from the current + baseline fingerprints; the harness only supplies them | One comparability authority; the runner passes `baseline=` + `comparison_requested=`. |
| No baseline configured | `baseline=None`; with `comparison_requested` the core resolves `missing_baseline` | A required-baseline gate then **blocks** (never a fabricated regression). |
| Promotion | `promote(record, path)` — an **explicit** act (the `evalglass baseline update` command, EG-M2-2b), never during an ordinary `run` | A run that could promote its own baseline could never regress against itself. |

## Consequences

- Comparability and the verdict stay a pure function of the core; the harness
  loads files and never decides comparability itself.
- A vanished or corrupt baseline is loud (setup error), not a silent downgrade.
- Baselines change only when a human runs the promotion command, so a green
  regression gate always compares against a deliberately chosen prior run.

## Alternatives considered

- **A slim bespoke baseline schema** (just the fingerprint). Rejected for now —
  reusing the `RunRecord` avoids a second serialization contract and keeps the
  promoted baseline fully reviewable (verdict, scores, diagnostics).
- **Auto-promote on a passing run.** Rejected — it manufactures comparability and
  defeats the point of a baseline.
- **Treat a missing baseline file as "no baseline".** Rejected — a configured path
  that does not resolve is a misconfiguration, not an absence; failing closed
  prevents a required-baseline gate from quietly downgrading.
