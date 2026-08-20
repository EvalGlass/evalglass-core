# ADR 0019 — ScoreSink export lane contract

- **Status:** accepted
- **Date:** 2026-05-31
- **Extends:** ADR 0008 (exit-class taxonomy), ADR 0017 (extension-lane framework)

## Context

A host wants to publish EvalGlass results to an external system (a dashboard, a CI
artifact store, a backend). The danger is that an export sink mutates the verdict,
authority, or CI exit, or that a sink failure hides/alters the core verdict — the
Scorecard JSON must remain the single source of truth (build contract §6/§8/§9).
The core `ScoreSink` port renders an immutable Scorecard to text; export is a
*different* operation (publish, not render) and belongs in an opt-in lane (ADR 0017).

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Shape | a **lane-local** `ScorecardExportSink` protocol (`export(scorecard) -> LaneResult`), distinct from the core `ScoreSink.render` | **No new core port**; the core port stays minimal and stable. |
| First sink | `FileScorecardExportSink` — publishes the Scorecard JSON to a local export dir (a **stub** for a backend upload / CI export) | Stub-first (consistent with ADR 0018); stdlib only, no network/SDK; a real uploader is a deletable follow-up behind the same shape. |
| Immutability | the sink reads `scorecard.to_dict()` only; it never holds or mutates the typed Scorecard | Proven by `check_scorecard_unchanged` (byte-identical before/after). |
| Failure | a failed publish → `LaneResult(blocked, [Diagnostic])`; the core verdict/authority/CI exit are untouched | A sink failure is never a changed verdict and never hides the verdict. |
| Authority | a `LaneResult` carries no score/verdict/authority — exporting grants nothing | One verdict path (build contract §2). |
| Opt-in / deletion | no destination → `MissingPrerequisite` (skip); registered as the `score-sink-export` lane; no required path imports it | Deleting it leaves the local JSON + Markdown reports intact (import-boundary guard + `verify-deletion`). |

## Consequences

- Results can be published externally while the Scorecard JSON stays authoritative;
  a sink can neither rewrite a verdict nor suppress one.
- A publish outage is an honest diagnostic, not a changed or hidden verdict.
- The export sink is opt-in and deletable; removing it changes no required output
  and leaves local reports intact.
- A real backend uploader is a drop-in replacement of the file write, behind the
  same `export(scorecard) -> LaneResult` shape and the same immutability guarantee.

## Alternatives considered

- **Add an `export` method to the core `ScoreSink` port.** Rejected — it widens a
  stable core port for an optional concern; a lane-local protocol keeps the core minimal.
- **A real HTTP/backend uploader now.** Deferred — it adds a network/SDK surface
  before the immutability + failure-isolation contract is proven; the file stub proves
  both hermetically and the uploader is a deletable follow-up lane.
- **Let a sink failure mark the run blocked.** Rejected — the run's verdict is the
  core's; a publish failure is a lane diagnostic, never a verdict change (ADR 0008).
