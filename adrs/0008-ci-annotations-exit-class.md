# ADR 0008 — CI annotations and the exit-class taxonomy

- **Status:** accepted
- **Date:** 2026-05-30
- **Extends:** ADR 0005 (harness CLI and exit codes)

## Context

M2's exit criterion is *CI can pass, fail, block, or report informational solely
from the core verdict payload* (build contract §10; EG-M2-3). M1 shipped the
exit-code split inline in the CLI (`0` pass/informational, `1` fail/blocked, `2`
setup) but had no named taxonomy and no CI-annotation surface. Two risks make
this worth recording before code lands:

- **A second verdict path.** If the CLI, a sink, or CI logic recomputed pass/fail
  from metric values or thresholds, EvalGlass would have two verdict authorities —
  the exact failure mode the single Verdict Engine exists to prevent
  (`CLAUDE.md §4/§11`).
- **Collapsing infrastructure failure into quality.** A subprocess crash, missing
  file, or adapter error reported as a `fail`/`blocked` quality verdict (or a
  `0.0` score) is false confidence: it implies a measured quality claim where none
  exists (build contract §8).

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Exit class | `harness/exits.py` `ExitClass` enum: `zero` · `nonzero_fail` · `nonzero_blocked` · `infrastructure_error` | A typed taxonomy, not bare ints. |
| Class source | `exit_class_for(scorecard)` is a fixed lookup over `scorecard.verdict.verdict` | Derived only from the core `VerdictPayload`; never recomputed from metrics/thresholds. |
| Exit codes | `zero`→0 · `nonzero_fail`→1 · `nonzero_blocked`→1 · `infrastructure_error`→2 | Preserves the ADR 0005 contract; `2` is a distinct class, never a quality verdict. |
| Infra path | The CLI returns `exit_code(ExitClass.INFRASTRUCTURE_ERROR)` on `SetupError`/`OSError` before a verdict exists | An infrastructure failure has no Scorecard, so it is not derivable from one — it is its own class. |
| CI annotations | `adapters/ci_annotation_sink.py` `CiAnnotationSink` (a `ScoreSink`); `evalglass run --format ci` | GitHub workflow commands rendered from Scorecard fields. |
| Annotation vocabulary | verdict words sourced from the `Verdict` enum; gate state via the shared `harness.report.gate_state` | No verdict string literals (the M1 scan-gate lesson); no duplicated gate-state logic. |
| Cited fields | metric, value, status counts, gate state, verdict reason code, authority reason, diagnostics | All present in the Scorecard. The literal approved **threshold** is *not* cited — it is not a Scorecard field, and the sink renders only what the Scorecard holds. |

## Consequences

- CI behavior (exit code and annotations) is a pure function of the core verdict
  payload; there is no second verdict path.
- Infrastructure errors stay distinguishable from quality failures at the process
  boundary, so a green/red signal always means what it says.
- The CI sink is an immutable rendering: like the Markdown/terminal sinks it
  cannot invent authority absent from the Scorecard, and deleting it leaves the
  verdict, exit code, and other reports unchanged.
- If the literal approved threshold is later wanted in CI output, it must first
  become a typed Scorecard field via a deliberate, matrix-tested core change — not
  fabricated in the sink.

## Alternatives considered

- **Recompute the exit decision from `ci_should_fail` in the CLI.** Equivalent for
  `0`/`1`, but it loses the named `infrastructure_error` class and invites
  per-call-site exit logic. A single typed taxonomy keeps the mapping in one place.
- **Cite a fabricated threshold in annotations.** Rejected — it is not in the
  Scorecard; printing it would be the sink manufacturing authority.
- **Put the CI sink in `harness/report.py` beside the other sinks.** The build plan
  places concrete sinks that may later gain backend variants under `adapters/`;
  the shared `gate_state` helper is imported from `report.py` to avoid duplication.
