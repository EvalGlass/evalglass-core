# ADR 0056 — Explicit metric source and evidence bindings

**Status:** Accepted

## Context

A metric's source names were not execution bindings. `metric.dataset` only referenced a dataset by
name for a reference lookup; a metric otherwise scored *every* loaded subject — the union of every
configured dataset, trace, and enabled trace lane. Two consequences, confirmed by field evaluation
of a real multi-workflow agentic app:

- **Population is imprecise.** A config that mixed a validated candidate dataset with unrelated
  proposed traces scored every metric over both, so a metric's population did not describe the
  evidence its construct actually consumes.
- **Authority is diluted globally.** Because population was run-global, authority had to be resolved
  from the *worst* source across the whole run (`runner._run_authority`); an unrelated proposed
  trace could dilute a metric bound, in intent, to validated gold.

The fix begins by making a metric declare, explicitly, which sources provide its candidate,
reference, context, and observation evidence, so both the executed population and (subsequently)
authority match the declared inputs. This ADR covers the binding contract; resolving authority over
the consumed set is a separate, dependent change.

## Decision

Add an **additive, optional** source-binding contract.

- **`SourceBinding` + `SourceRole`** (`harness/config.py`). A metric may declare
  `sources: [{name, role}]`. `SourceRole` is domain-neutral and authority-free —
  `candidate` (the subjects the metric scores), `reference` (gold/silver for a reference lens),
  `context`, and `observation` (supporting/assembled evidence). A role says only *how* a source is
  consumed; it never asserts the source is validated or that the metric may gate.
- **Resolution is fail-closed** (`RuntimeConfig`, where every source name is visible). Each binding
  name must resolve to exactly one known dataset or trace; a name that is both a dataset and a trace
  is ambiguous; a duplicate `(name, role)` and a metric that binds sources but no `candidate` role
  are setup errors; and declaring both `dataset` and `sources` is ambiguous (migrate the dataset
  into a candidate binding). These are setup errors with actionable messages, never silent drops.
- **A bound metric's population is only its candidate sources** (`harness/plan.py`). `build_plan`
  receives, parallel to the loaded subjects, each subject's configured-source name; a bound metric's
  `available`/`selector_matched`/`eligible` ledger is computed over only its `candidate` sources,
  then its selector. A run-integrity (route-error) subject is **never** filtered out of a bound
  metric's population, so an incomplete-input run still blocks a bound active gate.
- **Scoring honors the binding, not just the plan.** So the scored population equals the planned one,
  the Harness stamps each subject's source name into a reserved `Example.metadata` key and ANDs a
  source-membership constraint onto the metric's scoring selector — reusing the one
  `ExampleSelector` applicability implementation (integrity subjects still bypass) rather than
  teaching the core about sources. A bound metric therefore scores only its candidate sources; an
  unbound metric's examples and selector are untouched (byte-identical).
- **Bindings are score-determining.** A bound metric's resolved bindings enter the plan fingerprint
  and the per-metric authority provenance dimension, so changing a binding breaks comparability. The
  fields are emitted **only when bindings are declared**, so an unbound legacy metric keeps its exact
  pre-binding plan digest and provenance — existing baselines stay comparable across the upgrade.
- **Unbound metrics are unchanged.** A metric with no `sources` (with or without `dataset`) keeps the
  all-source population and the conservative run-global authority. `preflight`/dry-run prints each
  metric's resolved bindings and its available/matched/eligible counts.

## Consequences

- A developer can run disjoint metrics over separate sources in one config, and see — before any
  effect — exactly which sources each metric consumes and how many subjects that implies.
- The binding is the precondition for resolving authority over consumed evidence and for honest
  per-metric population accounting; both build on the resolved candidate set recorded here.
- Source I/O and history selection stay in the Harness; the binding *meaning* (roles, population
  scoping, provenance) is typed and lives with the plan/config contracts. The single Verdict Engine
  is untouched — bindings change which evidence a metric consumes, never who decides the verdict.
- Backward-compatible: a no-`sources` run is byte-identical (population, plan digest, provenance,
  artifacts); `metric.dataset` is preserved.
