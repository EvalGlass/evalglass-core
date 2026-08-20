---
name: reading-a-scorecard
user-invocable: false
description: >-
  How to read and explain an EvalGlass Scorecard and RunRecord honestly. Use when reporting,
  viewing, or explaining evaluation results (backs /evalglass view and /evalglass explain).
  Treats scorecard.json and runrecord.json as the primary truth and Markdown as rendering only;
  reports verdict and authority state first, numbers second; never reads a blocked or
  non-evaluable metric as 0.0, and never calls an informational run "passing".
---

# Reading a Scorecard

This backs **`/evalglass view`** and **`/evalglass explain`**. The typed artifacts are the truth:
`evals/reports/<run>/scorecard.json` (the compact, authority-aware summary) and `runrecord.json`
(the complete record — config, scores, provenance, verdict). `report.md` and the self-contained
`report.html` dashboard (verdict hero, KPI tiles, per-metric **interval bands**, an authority panel,
and a delta vs the previous run) are both **renderings** of the Scorecard; never treat their prose
as a source of authority the JSON does not carry.

## The verdict comes first, numbers second

Read `scorecard.verdict` (the `VerdictPayload`) and report it **before** any score:

- **informational** — no metric has gating authority. Real signal may be present, but nothing is
  being gated. Exit 0. **This is not "passing".**
- **pass** — every active gate is validly measured, comparable where required, and above its
  **approved** threshold. Exit 0.
- **fail** — an active gate is validly measured below an approved threshold. Exit non-zero.
- **blocked** — an active gate could not make an honest claim (missing evidence, non-evaluable,
  policy-forbidden, missing comparable baseline, **too few effective samples**, …). Exit non-zero.

Echo the verdict EvalGlass emitted; **never recompute or infer it**.

## `view` — per-metric status (v1)

For each metric report its **status** and **validity**, then its value only when the status is
`scored` and validity is `valid`:

- `scored` — a meaningful value. `blocked` / `non_evaluable` / `skipped` / `error` — **no value**;
  show the status and its diagnostic. **Never render a non-scored metric as `0.0`** — a missing or
  invalid measurement is not low quality; the explicit gap is the point.

When a metric is `scored`, the Scorecard also carries its **`Estimate`** — the point value (which
reuses the same aggregation, so it never disagrees with the metric) plus a **confidence interval**
(Wilson for proportions, Student-t for means) and the **effective n**. Report the interval, not just
the point: at small n or at `p ∈ {0,1}` the band stays wide — three-of-three is evidence, not proof.
Where a gate is active, echo its **decision statistic** — the safe default gates on the **lower
confidence bound**, not the bare point — as a typed field; never infer it.

Per-LLM-call reporting (`view --by-call`) groups `runrecord.json` scores by their **explicit
subject identity** — each `Score` carries its `example_id`/`unit_id` (framework slice F1) — so the
grouping is *read*, never invented from list order. Report each call's status/validity/diagnostics
the same way (never `0.0` for a non-scored call). If a score lacks identity (an older artifact), say
so and do not guess. Mapping a score back to its **source function** is a separate
advanced extension (it needs trace↔call-site correlation that does not exist yet) — not this view.

## `explain` — why a number is or isn't trustworthy

Narrate strictly from typed fields — authority state (dataset `proposed`/validated; threshold
`proposed`/`approved`; judge uncalibrated/calibrated/drifted; data policy), provenance, and
diagnostics. For each metric, say what's real signal vs what's inert and **why** (e.g. "reference
metric is blocked: the dataset is `proposed`, not validated gold"). **Add no claim that is not
backed by a field in `runrecord.json`.** Do not say a result "looks fine".

## Comparisons

A delta is meaningful only when `baseline_state` is `comparable`. If it is `not_comparable`,
`missing_baseline`, or `comparison_not_requested`, report that state and the differing fingerprint
dimension — never a bare number that implies a regression the provenance does not support. When it
*is* comparable, the delta is an **item-level paired comparison** over shared `example_id`s with its
own interval; a metric reads as **improvement** / **regression** only when that interval clears
zero, else **`within_noise`**.

The **`evalglass-honesty`** guardrail applies to every sentence you produce here.
