---
name: authoring-a-metric
user-invocable: false
description: >-
  How to add an EvalGlass metric to a host repo (backs /evalglass add-metric). Scaffolds a
  MetricSpec in evals/evalglass.yaml as proposed/informational so it cannot gate by default;
  distinguishes built-in metrics from host-evaluator metrics; and explains the non-reference,
  reference, and judge prerequisites honestly. Never writes an approved threshold or a validated
  dataset status — granting authority is the host's explicit act.
---

# Authoring a metric

This backs **`/evalglass add-metric`**. A metric is a `MetricSpec` entry in the host's
`evals/evalglass.yaml`. You (the agent) add it; the **host** validates it. Everything you scaffold
lands **`proposed`/informational** and **cannot gate** until the host earns authority — see
`promoting-a-gate`.

> **You decide _what_ to measure; this skill scaffolds it.** EvalGlass is the framework, not the
> oracle — it does not derive metrics for you. The host names the check the app needs (a failure to
> catch, a contract to enforce, an output rule); this skill turns that into a `MetricSpec` across the
> runtime / reference / judge tiers. If you're unsure which tier fits, prefer the cheapest honest one
> (a deterministic runtime built-in) before reaching for gold or a judge.

## Add the MetricSpec (proposed by default)

Append a metric to `metrics:` with its `name`, `evaluator_ref`, `lens`, and `score_type`. Do **not**
set `metric_status: gating`, `threshold_approval: approved`, or a dataset `status: validated` — leave
them at their authority-safe defaults so the metric is informational.

Choose the metric kind honestly:

- **Non-reference built-in** (`structural_shape`, `field_presence`, `trajectory_shape`) — runs
  immediately and produces real signal with **no gold and no calibration**. The best first metric.
- **Reference built-in** (`exact_match`, `set_overlap`) — needs host **gold**; it scaffolds as
  *needs host gold* and **cannot gate on a `proposed` dataset**.
- **Judge metric** (`judge_score`) — needs **calibration**; it scaffolds as *needs calibration* and
  cannot gate while uncalibrated (see `calibrating-a-judge`).
- **Host-evaluator metric** — points `evaluator_ref` at a host-owned evaluator you author (see
  `writing-a-host-evaluator`); it lives outside `evals/_evalglass/` and stays host-owned.

## What you never do

- Never set an **approved** threshold or a **validated** dataset status for the host — that is the
  host's deliberate act, recorded in `evals/authority.json` (empty by default).
- Never describe a freshly added metric as "passing" or "safe"; a new metric is informational.

After adding it, run `/evalglass run` and read the result with `reading-a-scorecard`: the new metric
shows real signal (non-reference) or a `blocked`/`non_evaluable` status with a diagnostic explaining
the missing gold/calibration — never `0.0`.
