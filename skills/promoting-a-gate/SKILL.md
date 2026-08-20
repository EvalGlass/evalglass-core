---
name: promoting-a-gate
user-invocable: false
description: >-
  Guidance for a host turning an informational EvalGlass metric into a gate. Use when someone asks
  to "make a metric gate", enable CI blocking, or promote a gate. This is guidance only — there is
  no /evalglass verb that promotes, approves, or certifies a gate. Gate activation is the host
  editing host-owned YAML after validating gold, approving a threshold, calibrating judges where
  used, and confirming baseline comparability and data policy.
---

# Promoting a gate (host-owned)

This skill is **guidance only**. There is deliberately **no command that promotes a gate** — no
verb gates, approves, or certifies. Activating a gate is a host decision, made by editing
host-owned YAML; EvalGlass cannot "make it pass" for you. Your job here is to *explain* the
checklist, never to perform the approval.

## What the host edits (in `evals/evalglass.yaml` and `evals/authority.json`)

A metric gates only when all of its prerequisites are host-validated:

1. **Validate the gold** — replace sample data with real gold and set the dataset
   `status: validated` (a reference metric cannot gate on a `proposed` dataset).
2. **Approve a threshold** — set a `threshold` and `threshold_approval: approved`, recorded with a
   real approver in `evals/authority.json`. Optionally set a **decision policy**: by default a gate
   decides on the **lower confidence bound** of the estimate (not the bare point) and **blocks** when
   the effective n is below `min_n_effective` or missing data exceeds `max_missing_fraction`, so a
   lucky small sample cannot clear the bar; a low-assurance point check must be *named* explicitly
   (a `point` policy).
3. **Calibrate judges** (if the metric is a judge) — record calibration evidence first
   (`calibrating-a-judge`); an uncalibrated or drifted judge cannot gate.
4. **Confirm baseline comparability** — for a regression gate, ensure the run is `comparable`
   (matching fingerprint dimensions); a `not_comparable` baseline cannot support a regression claim.
5. **Review data policy** — declare each dataset/trace `data_policy`.
6. **Set `metric_status: gating`** — only after 1–5 hold.

Once approved, the authorization is a **digest-bound `AuthorityGrant`** — content-addressed to the
things it approved (dataset, threshold, decision policy, judge study). Edit any bound artifact and
the approval stops matching, so the run drops to `informational`/`blocked` rather than silently
gating on a stale grant; an approval is never transferable between runs by name alone.

## The honest framing

Until the host completes this checklist, the metric is **informational** and a non-failing run is
**not** "passing". The Verdict Engine — not this skill, not any verb — resolves the gate from the
host's validated state. Walk the host through the checklist; let them make each edit.
