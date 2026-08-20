---
name: evalglass
argument-hint: "[setup | connect | run | view | explain | compare | baseline | ci]"
description: >-
  Honest, local-first AI quality control for an agentic app's LLM calls. Use when the user types
  /evalglass or asks to set up, run, view, explain, compare, baseline, or wire CI for an EvalGlass
  evaluation. Routes a verb (setup, connect, run, view, explain, compare, baseline, ci) to the
  right action; bare /evalglass prints an honest status dashboard and runs nothing. EvalGlass
  measures and reports only what the evidence supports — it never decides quality for you and
  never makes a run "pass".
---

# EvalGlass — `/evalglass <verb>`

EvalGlass gives an agentic project **grounding**: honest, typed metrics and a Scorecard whose
claims never exceed the evidence. You direct; the agent does the work; **the host validates and
the runtime decides** — the plugin only types commands and reads back typed artifacts.

> **The rule this skill never breaks.** A green or non-failing EvalGlass run never implies more
> evidence, authority, calibration, comparability, or safety than the run actually earned. This
> skill has **no** verb that gates, approves, certifies, validates, or makes a run "pass" — those
> are the host's, resolved only by the Verdict Engine.

## Bare `/evalglass` — status dashboard (runs nothing)

When invoked with no verb, **report state and the next honest step; do not run, write, or mutate
anything.** Read only what already exists in the repo and say plainly what is and isn't true:

- **Integration:** is `evals/_evalglass/` present (EvalGlass vendored) or not yet?
- **Call-site scan:** if a previous `setup --scan-only` left a report, how many *candidate* LLM call
  sites were found (a heuristic inventory — not "all" calls).
- **Data:** any `evals/datasets/*.jsonl` or `evals/traces/*.jsonl`? Note datasets default to
  `proposed` (not validated gold).
- **Metrics / authority:** which metrics are wired; whether any threshold is `approved`, any judge
  `calibrated`, `evals/authority.json` populated. Default state is **informational** — nothing gates.
- **Next honest step:** the single most useful verb to run next (e.g. "run `/evalglass setup` to
  vendor the runtime", or "`/evalglass run` to produce a Scorecard").

If you cannot determine a state, say so — never guess a number or imply coverage.

## Routing a verb

Each verb is an instruction to issue an **exact Bash command** and read back typed artifacts.
The skill body does not execute; you (the agent) run the command. Keep the **three execution
targets** distinct and never mix them:

- **Integration-time** (discover / plan / install / re-vendor) → the **bundled** framework via the
  launcher: `"${CLAUDE_PLUGIN_ROOT}/bin/evalglass-launch" <cmd> --root .` (a marketplace-only user
  has no pip-installed `evalglass-install`; the launcher puts the bundled `src/` on `PYTHONPATH` and
  runs `python -m evalglass.installer`). Setup errors there exit `2` and are *setup* diagnostics.
- **Host evaluation** (`run`, `baseline`) → the host's **vendored** runtime, never the framework
  package, never via import: `PYTHONPATH=evals python -m _evalglass.harness.cli …`.
- **Quickstart demo** (pre-install) → the **bundled** example via the bundled framework:
  `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python -m evalglass.harness.cli run --config "${CLAUDE_PLUGIN_ROOT}/examples/quickstart/evals/evalglass.yaml"`.

`${CLAUDE_PLUGIN_ROOT}` is the **Claude Code** plugin-root variable; on a runtime without it
(e.g. a Codex install, which ships skills only), use the always-portable direct CLI
`python -m evalglass.installer <cmd> --root .` with the `evalglass` package importable.

When you report any result, lead with the **non-reference** signal (`structural_shape`,
`field_presence`) — it is the real, populated, no-gold/no-calibration evidence — and keep the
verdict **informational** until the host has earned authority.

| Verb | What you do | Execution target |
|---|---|---|
| `setup` | discover candidate call sites (announced, read-only, consent-gated; resolve every data-policy prompt with the host **before any write**), then vendor the runtime + scaffold a `proposed` starter dataset, metrics, and CI; flags `--scan-only` (discover only), `--dry-run` (plan + managed-file diff), `--ci` (copy CI), `--upgrade` (re-vendor managed files, diff + explicit confirm) | bundled launcher: `evalglass-launch discover\|plan\|install\|revendor` |
| `connect` | import the host's **exported** OTel/OpenInference-shaped JSON or local trace JSONL (hermetic, no SDK, no network), or scaffold a `proposed` starter dataset from scanned calls/traces; enforce data policy first. `connect --live <platform>` is a **wired, opt-in** verb (ADR 0046) that scaffolds a deletable Langfuse/Phoenix/LangSmith lane into `evalglass.yaml` (env-ref credentials, fail-closed egress, forced `proposed`) — the following `run` does the pull; `connect --synth` is governance-only (no generator) — see the note below | host config + bundled launcher |
| `run` | run the evaluation and read the verdict | host's **vendored** runtime: `PYTHONPATH=evals python -m _evalglass.harness.cli run --config evals/evalglass.yaml` |
| `run --example quickstart` | the pre-install demo — populated non-reference signal + an honest **informational** verdict with diagnostics | **bundled** example + framework (see above) |
| `view` | read `scorecard.json` / `runrecord.json`; report **per-metric** status+validity, status counts, baseline state (never `0.0` for a blocked/non-evaluable metric). `--by-call` groups `runrecord.json` scores by their **explicit subject identity** (`example_id`/`unit_id`), never by list order — report each call's status/validity/diagnostics; if a score lacks identity (an old artifact), say so and do not guess. Score-to-source-function mapping is a separate advanced extension, not this view | read typed artifacts only |
| `explain` | narrate *why* each number is or isn't trustworthy, strictly from the typed authority/diagnostics/baseline fields; a missing field is reported as missing evidence, not inferred | read typed artifacts only |
| `compare` | compare against a baseline; show a delta **only** when the typed comparability claim is `comparable`, else name the differing fingerprint dimension | read typed artifacts only |
| `baseline` | promote a baseline — a deliberate, explicit act, never automatic | host's vendored runtime: `PYTHONPATH=evals python -m _evalglass.harness.cli baseline update …` |
| `ci` | copy the scaffolded `evals/ci/github-actions.yml` verbatim (alias of `setup --ci`); the workflow invokes only the vendored runtime and exits on `ci_should_fail` — it adds no verdict logic, references neither the plugin nor the launcher, and blocks only after the host approves a gate | scaffold copy |
| `run --example quickstart` | v1 *(EGP-P1)* | the pre-install demo: run the **bundled** example via the **bundled** framework (no host runtime exists yet) | bundled example |

### v1.1 — authoring tier (subcommands; scaffold host-owned truth, never authority)

These help a host author its own measurement. Every asset they scaffold stays **`proposed`/
uncalibrated/empty-authority** (ADR 0025); none can gate until the host validates it.

| Verb | What you do | Backing skill |
|---|---|---|
| `add-metric` | append a `MetricSpec` to `evals/evalglass.yaml` as `proposed`/informational (built-in or host-evaluator); never an approved threshold or validated dataset | `authoring-a-metric` |
| `add-judge` | scaffold an **uncalibrated** `judge_score` metric + a rubric; it cannot gate until calibrated | `calibrating-a-judge` |
| `calibrate` | help the host record **host-owned** calibration evidence under `evals/calibration/`; never self-approve a gate | `calibrating-a-judge` |

Authoring a custom scorer → `writing-a-host-evaluator` (host-owned, imports only `_evalglass.core`,
never `0.0` for a non-scored state). Turning a metric into a gate is **host-owned** and has **no
verb** — point the host at `promoting-a-gate` (validate gold → approve a threshold → calibrate →
confirm comparability → set `metric_status: gating`). If a verb's machinery is not built in this
repo, say so plainly and point at the backing skill — do not pretend it ran.

**Deciding _what_ to measure.** EvalGlass supplies the machinery, not the metric set — the host
decides what to check. When the host describes a check they want ("flag any answer citing a source
outside the retrieved context", "the summary must stay under 40 words", "`status` must be one of
these five values"), route to **`authoring-a-metric`**, which scaffolds it into `evals/evalglass.yaml`
as a `proposed`/`informational` metric across the three tiers (runtime / reference / judge). The host
directs; the agent scaffolds; every asset stays non-authoritative until the host validates.

**Advanced connectors** (`evaluate-an-agentic-app`): `connect --live <platform>` is now a **wired,
opt-in verb** (ADR 0046) that scaffolds a deletable Langfuse/Phoenix/LangSmith connector lane into
`evalglass.yaml` — env-ref credentials (never literal secrets), data-policy-first (fail-closed egress),
clean-skip on missing prerequisites, no provider SDK on any required path; a live pull is `proposed`
data and cannot gate. `connect --synth` is governance-only (no generator — generated data would be
`proposed`, never gold); per-source-function views remain unbuilt (`plugin-docs/advanced-source-correlation.md`).

## Honest framing of every result

Whenever you report a result, the **`evalglass-honesty`** skill applies: state the verdict and
authority/calibration/comparability state **first**, numbers second; call a clean run
**informational**, never "passing", until a host has earned the authority. Reference the bundled
agent-reference in `plugin-docs/` rather than inventing claims.

## Boundaries (ADR 0022)

- Never edit files under `evals/_evalglass/` by hand — they are managed and re-vendored.
- Never populate `evals/authority.json`, approve a threshold, or calibrate a judge *for* the host.
- Never write provider SDKs or secrets into scaffolded assets.
- Nothing this skill writes into the host may reference the plugin — the runtime must work after
  the plugin and the agent are removed.
