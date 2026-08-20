---
name: installing-evalglass
user-invocable: false
description: >-
  How to integrate EvalGlass into a host repo: discover candidate LLM call sites (read-only),
  resolve data-policy questions with the host, plan the managed/host-owned split, vendor the
  runtime under evals/_evalglass/, scaffold host-owned starter assets with safe (informational)
  defaults, and stop for human validation before anything can gate. Backs /evalglass setup.
  Integration-time only — the vendored runtime runs on its own afterwards.
---

# Installing EvalGlass into a host repo

This backs **`/evalglass setup`**. The engine is deterministic Python; this recipe drives it and
adds the judgment the mechanical steps cannot make (reading LLM call sites, answering data-policy
questions). It is **integration-time only** (ADR 0010/0022): once installed, the vendored runtime
under `evals/_evalglass/` runs on its own — no dependency on this skill, the plugin, or any agent.

> **The rule it never breaks.** A green or non-failing run never implies more than the evidence
> earned. The skill **never grants authority**: scaffolded gold is `proposed`, thresholds are
> `proposed`, judges are uncalibrated, and `evals/authority.json` is empty. A fresh install's first
> run is **informational**. Only the host, after validating, turns a metric into a gate.

## Two ways to run the skill engine

- **Plugin (marketplace) user:** run the **bundled** framework from the plugin —
  `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python -m evalglass.installer <cmd> --root .`
  (the `${CLAUDE_PLUGIN_ROOT}/bin/evalglass-launch` wrapper lands in EGP-P1).
- **Direct / existing user (unchanged):** `python -m evalglass.installer <cmd> --root .` when the
  `evalglass` package is importable. **This path is preserved** — the plugin is additive, and it is
  the portable path on any runtime without `${CLAUDE_PLUGIN_ROOT}` (e.g. a Codex install, which
  ships skills only — no bundled launcher).

`<cmd>` is one of `discover | plan | install | revendor`.

## Recipe

1. **Discover (read-only).** Announce that you will scan the repo for *candidate* LLM call sites —
   a heuristic inventory, not a claim to find *all* calls — and ask consent. Then:
   `python -m evalglass.installer discover --root .`
   Review the `HostDiscoveryReport`: language, candidate call sites, prompts, existing eval assets,
   CI, and any `DataPolicyPrompt`s. **Resolve every data-policy prompt with the host before any
   write — never assume `permitted`.**
2. **Plan.** `python -m evalglass.installer plan --root .` — show the non-authoritative install plan
   (managed vs host-owned split, proposed scaffolds) and confirm before mutating.
3. **Install.** `python -m evalglass.installer install --root .` — vendor the managed runtime and
   scaffold host-owned starter assets; existing host files are preserved, never overwritten.
4. **First run.** `PYTHONPATH=evals python -m _evalglass.harness.cli run --config evals/evalglass.yaml`
   — expect **informational** / exit 0. This is correct, not a gate. (Backs `/evalglass run`.)
5. **Wire CI** *(optional, `--ci`)*. Copy `evals/ci/github-actions.yml` into `.github/workflows/`.
   It invokes only the vendored runtime and exits on the core `ci_should_fail` — it adds no verdict
   logic and blocks only once the host has approved a gate.
6. **Confirm with the human.** Hand off the validation checklist in `evals/README.md`: validate
   gold, approve a threshold, calibrate judges, choose a baseline, review data policy, activate the
   gate. Until then, everything stays informational.

> **Deciding what to measure.** `setup`'s scan is a *call-site* inventory, not a metric set —
> EvalGlass supplies the machinery, not the metrics. You decide which checks the app needs; tell the
> agent and route to **`authoring-a-metric`**, which scaffolds each as a `MetricSpec` (runtime /
> reference / judge tiers) into the canonical `evals/evalglass.yaml`, `proposed`/`uncalibrated`. The
> host directs; the agent scaffolds; the host validates.

## Upgrades

`/evalglass setup --upgrade` re-vendors managed files (`python -m evalglass.installer revendor`): it
runs a dry-run diff and requires explicit confirmation before touching a host-patched managed file,
and it replaces only files under `evals/_evalglass/` — host-owned truth is never clobbered.

## Boundaries

- Never edit `evals/_evalglass/` by hand. Never populate `evals/authority.json` for the host.
- Never write provider SDKs or secrets into scaffolds.
- Host code must keep working after the plugin and skill are removed; never make host code import
  `evalglass.installer` or reference the plugin.
