---
name: calibrating-a-judge
user-invocable: false
description: >-
  How to add and calibrate an LLM-judge metric in a host repo (backs /evalglass add-judge and
  /evalglass calibrate). A new judge is uncalibrated and cannot gate; calibrate records host-owned
  calibration evidence and never self-approves a gate. Judge parser or provider failures are
  diagnostics or non-scored states, never low scores. Approved thresholds plus calibration are
  prerequisites before the Verdict Engine can gate a judge metric.
---

# Calibrating a judge

This backs **`/evalglass add-judge`** and **`/evalglass calibrate`**. A judge metric (`judge_score`)
scores with an LLM rubric. It is powerful and easy to over-trust, so EvalGlass makes calibration a
hard prerequisite: an **uncalibrated** judge **cannot gate**, no matter its numbers.

## `add-judge` — scaffold an uncalibrated judge

Add a `judge_score` metric to `evals/evalglass.yaml` and a rubric under `evals/rubrics/`. It lands
**uncalibrated** and informational. In required/local flows the judge uses **fake judge evidence**
(hermetic, no network). For a real judge inside a config-driven run, the **host command judge**
(`judge: {adapter: command}`, a host script under `evals/judges/<name>.py`) shells out over a JSON
contract; live provider lanes (`live-judge`, `openai-judge` for an OpenAI-compatible endpoint) stay
opt-in and never sit on a required path. All of these — fake, command, and live — produce
**uncalibrated → informational** results until a study calibrates them; the lane is generic
transport and the host owns the rubric text.

## `calibrate` — record host-owned calibration evidence (computed, not declared)

Calibration is a **host-owned** act, and it is **computed, not declared**: the host supplies trusted
labels and EvalGlass computes a **`JudgeAgreementStudy`** — a confusion matrix, percent agreement,
**Cohen κ**, and order-bias — whose arithmetic is **re-verified on load**, so a hand-edited study is
rejected. `calibrate` helps record that host-owned evidence under `evals/calibration/`; it **never**
self-approves a gate and never marks a judge calibrated on the plugin's say-so. Calibration is bound
to the judge's **instrument identity** (`JudgeInstrument`: provider, model, seed, temperature, and
the content digests of the resolved prompt + rubric) — change the instrument and the judge reads as
**`drifted`**, re-opening calibration so old labels can't silently validate a new judge. A judge
metric can gate only once **both** a verified agreement study and an **approved** threshold exist
(see `promoting-a-gate`).

## What stays honest

- A judge parser failure, a provider error, or a malformed response is a **diagnostic** or a
  non-scored status (`blocked`/`error`) — **never** a low score and never `0.0`.
- `add-judge`/`calibrate` never populate `evals/authority.json` for the host.
- Until the host calibrates and approves, the judge is informational — report it that way with
  `reading-a-scorecard`, never as "passing".
