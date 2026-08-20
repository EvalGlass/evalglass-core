# ADR 0015 — Judge evidence, calibration, and threshold-approval record formats

- **Status:** accepted
- **Date:** 2026-05-31
- **Extends:** ADR 0014 (JudgeModel port), ADR 0009 (baseline file and explicit promotion — the same host-owned-record discipline)

## Context

A judge metric may gate only when a human has **calibrated** the judge and
**approved** a threshold (`CLAUDE.md §11/§14`). That authority must be typed,
host-owned data — not report prose and not a config toggle. M4 needs three record
formats, and each is **schema-open** host input, so each must fail closed. Two
trust hazards drive the decision:

- **Config self-declaring authority.** If `evalglass.yaml` could set
  `judge_calibration: calibrated` + `threshold_approval: approved`, any metric
  author could gate CI with no validated evidence — authority leaking from a knob
  (`CLAUDE.md §4/§19`).
- **A rubric change carrying a stale regression claim.** If the rubric, prompt,
  parser, or model changed but the baseline stayed `comparable`, a score delta
  would imply a regression that the changed evaluator never measured (`CLAUDE.md §11`).

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Judge evidence | core `JudgeEvidence` (frozen, JSON-primary, fail-closed `from_dict`, **public-JSON-snapshotted**): status, raw + parsed value, rationale, rubric/prompt/model/parser refs, token/cost/latency, response fingerprint | A non-`OK` status carries **no** parsed value; finite numeric fields validated in the constructor. |
| Calibration record | host-owned `CalibrationRecord` (`evals/calibration/*.json`, **outside** `_evalglass/`): status, approver, rationale, `variance_runs ≥ 2` for `calibrated` | The harness loads it and **derives** the `JudgeCalibration` enum; the core validates consistency. |
| Threshold approval | host-owned `ApprovedThreshold`: value, direction, `variance ≥ 0`, approver, rationale, version | A threshold missing any required field is **not** approved; direction must match the metric. |
| Authority derivation | the harness derives `JudgeCalibration` + threshold approval into `authority_inputs`; the core resolves authority | The core validates the record but **never invents an approver**. |
| Absent record | a judge metric with no `CalibrationRecord` ⇒ `UNCALIBRATED` + `PROPOSED` | yaml **cannot** self-declare `calibrated`/`approved`; authority comes from a validated record. |
| Provenance | rubric/prompt/parser/model refs + response fingerprint enter the gating provenance dimensions | A rubric- or parser-version change → `not_comparable`; an unrelated change stays `comparable`. |
| Malformed input | a present-but-malformed record is a **setup error**, never read as absent | Schema-open records fail closed (the validator-gate Slice-16 lesson). |

## Consequences

- Only a **calibrated** judge with a **complete, approved** threshold can gate, and
  it gates only through the single Verdict Engine (ADR 0008).
- An uncalibrated, calibrating, drifted, or retired judge metric stays
  informational/blocked — it cannot silently pass.
- A rubric/prompt/parser/model change shifts provenance, so no regression claim
  survives across an evaluator change.
- Provenance is computed from the **effective** (post-derivation) authority, not the
  raw config, so the fingerprint describes the authority the run actually used.
- Judge evidence is JSON-primary and snapshotted, so EGTS can inspect it as a
  stable artifact.

## Alternatives considered

- **A `judge_calibration` toggle in `evalglass.yaml`.** Rejected — it lets config
  manufacture authority with no validated evidence; calibration must come from a
  host-owned record.
- **Treat a malformed record as missing (→ uncalibrated).** Rejected — silently
  downgrading a malformed record hides a host mistake; a present-but-malformed
  record fails closed as a setup error.
- **Keep judge evidence untyped (a dict on the bundle).** Rejected — a typed,
  snapshotted contract is what lets the core parse it deterministically and lets
  EGTS prove non-scored states.
