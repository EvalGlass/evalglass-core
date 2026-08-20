# ADR 0025 — Authoring tier and advanced extensions (v1.1)

- **Status:** accepted
- **Date:** 2026-06-02
- **Reuses:** ADR 0022 (plugin packaging — no authority verbs), ADR 0016 (live judge lane), ADR 0017/0018 (optional-lane framework + trace-backend stub), ADR 0021 (generated-evidence governance), ADR 0024 (score subject identity)
- **Source:** `docs/PLUGIN_TRANSFORMATION_PLAN.md` §4.4 (v1.1), §9; `docs/plugin_transformation_jira_tickets.xlsx` (EGP-A1)

## Context

After the v1 path lands, hosts need help authoring metrics, host evaluators, judges, and
calibration, plus opt-in advanced connectors (live tracing platforms, synthetic data) and a future
per-source-function view. These surfaces carry **authority risk** — the pressure to "make it pass"
must never push the plugin into manufacturing gold, thresholds, calibration, or gates. This ADR
records how the authoring tier stays honest. It is delivery/packaging only — it wraps existing
framework capability (`skill/scaffold.py`, `harness/governance.py`, `harness/calibration.py`, the
`judge_live`/`trace_backend_stub` lanes) and adds **zero** framework code and **zero** provider SDK.

## Decision

1. **Authoring verbs scaffold `proposed`/uncalibrated/empty-authority — never authority.**
   `/evalglass add-metric`, `add-judge`, and `calibrate` are skill-routed verbs (the agent edits
   **host-owned** files; the host validates). A new metric lands `proposed`/informational and cannot
   gate; a new judge is uncalibrated and cannot gate; `calibrate` records host-owned calibration
   *evidence* and never self-approves a threshold. `authority.json` stays the host's to populate.

2. **No gate-activation verb.** Gate activation is the host editing host-owned YAML
   (`metric_status: gating`, `threshold_approval: approved`, `status: validated`), *guided* by the
   `promoting-a-gate` skill. The plugin ships no `promote-gate`/`gate`/`approve`/`certify` verb —
   the absence is the identity (ADR 0022 §9.9), enforced by `tests/plugin/test_skills.py` and
   `tests/plugin/test_authoring.py`.

3. **Host evaluators stay host-owned and import nothing of the plugin.** `writing-a-host-evaluator`
   guides authoring a `host-owned` evaluator (outside `evals/_evalglass/`) that returns typed
   `Score`/`ScoreBatch`, represents non-scored states with status + diagnostics (never `0.0`), and
   imports only the vendored `_evalglass.core` contracts — never the framework package or the plugin
   (runtime independence holds).

4. **Advanced connectors are opt-in, isolated, deletable optional lanes.** `connect --live`
   `<platform>` routes to the optional-lane framework (ADR 0017/0018): data-policy review first, a
   `MissingPrerequisite` clean-skip when prerequisites are absent, and **no required import path
   loads it** (the `tests/core_isolation` import-boundary guard proves deletion safety). EvalGlass
   ships **no provider SDK** — the live HTTPS judge lane is stdlib (`live-judge` extra); a real
   Phoenix/Langfuse trace adapter is an opt-in host extension over the `trace-backend` lane
   contract (stub today), not bundled.

5. **Synthetic data is governed, never validated.** `connect --synth` returns the governance truth
   (no generator is built) and, if a generator is added later, imports via
   `harness/governance.import_synthetic_dataset`, which **forces `proposed`** regardless of any
   declared status (ADR 0021). Generated data is never presented as validated gold.

6. **Per-source-function view stays an advanced, unbuilt extension.** Score subject identity (F1 /
   ADR 0024) enables `view --by-call`; mapping a score back to its *source function* needs
   trace↔call-site correlation that does not exist. `source-correlation` is a design note with
   explicit non-coverage language — not a shipped feature.

## Consequences

- The frozen core, the single Verdict Engine, typed authority, and no-false-confidence are
  untouched; A1 adds skills + verbs (prose) + docs + tests only.
- Optional-lane QA (EGP-A1-8) extends the honesty-audit, manifest-consistency, no-authority-verb,
  and deletion/prereq checks to every A1 surface, so the tier cannot drift into overclaim.

## Alternatives considered

- **A `promote-gate` verb** (a one-command gate activation). Rejected: it reads as "make it pass"
  and would manufacture authority; gate activation must be an explicit host YAML edit.
- **Bundling a Phoenix/Langfuse SDK for `connect --live`.** Rejected: it adds an un-hermetic
  provider dependency to a framework that is stdlib-only by design; the lane contract + stub + an
  opt-in host extension keep it deletable and honest.
- **Shipping a synthetic-data generator now.** Deferred: governance exists, a generator does not;
  `connect --synth` tells that truth rather than implying generated gold.
