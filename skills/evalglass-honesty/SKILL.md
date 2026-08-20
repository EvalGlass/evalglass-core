---
name: evalglass-honesty
user-invocable: false
description: >-
  Always-on guardrail for reporting EvalGlass results. Use whenever you are about to describe,
  summarize, paraphrase, or interpret an EvalGlass Scorecard, verdict, score, or comparison to a
  human. Forces honest scope: state verdict and authority/calibration/comparability state before
  numbers, and never paraphrase an informational or non-failing run as "passing", "safe", or
  "correct". Triggers on interpreting results, not on doing work.
---

# EvalGlass honesty guardrail

This skill triggers when you are about to **report or interpret** an EvalGlass result — not when
you run, scaffold, or set anything up. Its single job: make sure nothing you say about a run
implies more than the run earned.

> EvalGlass's reason to exist is **no false confidence**. A green or non-failing result must never
> be read as proof of more evidence, authority, calibration, comparability, or safety than the run
> actually has. Your wording must hold the same bar the Scorecard does.

## State first, numbers second

Lead every result summary with the typed state, then the figures:

1. the **verdict** (`informational` / `pass` / `fail` / `blocked`) exactly as EvalGlass emitted it;
2. the **authority** state — is any threshold `approved`, any judge `calibrated`, the dataset
   validated or `proposed`;
3. the **comparability** state for any delta (`comparable` / `not_comparable` / `missing_baseline`);
4. only then, the metric values — and only for metrics whose status is `scored` and `valid`.

## Required scope language

- An **informational** run means *no metric was authorized to gate* — say that. It is **not** a
  quality pass.
- A metric that is `blocked`, `non_evaluable`, `skipped`, or `error` has **no value**; report the
  status and its reason. Do **not** turn it into `0.0` or "low quality".
- A reference metric on `proposed` (un-validated) data, or a judge that is not calibrated, is
  evidence the host must validate — not a result that can gate.
- A regression claim is honest only when the baseline is `comparable`; otherwise name the differing
  fingerprint dimension instead of a number.

## Forbidden wording (do not use for an unearned result)

Never describe a non-failing or informational run as **"passing"**, **"passed"**, **"green"**,
**"safe"**, **"correct"**, **"verified"**, or **"production-ready"**. Never call EvalGlass output a
**"guarantee"** or **"proof of correctness"**. Never imply coverage the call-site scan did not claim
(it finds *candidate* call sites, not *all* of them). A passing Scorecard is **evidence, not
proof** — say it that way.

## Examples

- Informational run → *"Verdict: informational — no gate is active (the dataset is `proposed` and
  no threshold is approved). `structural_shape` scored 1.0 on N units; that is real signal about
  output well-formedness, not a quality pass."*
- Blocked gate → *"Verdict: blocked — `exact_match` is `blocked` because its dataset is `proposed`,
  not validated gold; EvalGlass refuses to make a quality claim it cannot support."*
- Non-comparable baseline → *"Baseline is `not_comparable` (the dataset changed `proposed`→
  approved), so there is no honest delta to report — only the changed dimension."*
