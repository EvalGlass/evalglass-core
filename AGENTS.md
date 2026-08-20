# EvalGlass — AGENTS.md (Codex runtime entry)

EvalGlass is an AI-safety evaluation framework for agentic apps, delivered as a plugin. It
measures the quality of an app's LLM calls from host-owned evidence and reports only what the
evidence honestly supports. It never decides quality for you and never reports a run as "passing":
**you direct, the host validates, and the runtime decides** — the plugin only types commands and
reads back typed artifacts.

This file is the Codex-runtime entry, parallel to the Claude Code `SessionStart` bootstrap
(`hooks/session-start.sh`). It is **display-and-routing only**: it reads no scorecard, runrecord,
verdict, authority, or gate state, and asserts no quality or capability claim.

## Using EvalGlass in a session

Say *"evaluate my agentic app with EvalGlass"*, or invoke the **`evalglass`** umbrella skill, to
begin. The umbrella routes a verb to the right backing skill under `skills/`:

- `setup` — discover candidate LLM call sites (read-only, consent-gated), vendor the runtime, and
  scaffold `proposed` starter assets.
- `connect` — import the host's exported OpenTelemetry/OpenInference JSON or local trace JSONL.
- `run` — run the evaluation against the host's vendored runtime and read the verdict.
- `view` / `explain` — read `scorecard.json` / `runrecord.json`; report status and authority
  state first, numbers second; never read a blocked metric as `0.0`.
- `compare` / `baseline` — compare runs only when the typed comparability claim says so;
  baseline promotion is deliberate, never automatic.
- `ci` — copy the CI scaffold; it exits on the core `ci_should_fail` only.
- *(v1.1)* `add-metric` / `add-judge` / `calibrate` — scaffold host-owned metrics, judges, and
  calibration evidence that stay `proposed`/uncalibrated and cannot gate until the host validates.

Deciding *what* to measure is **host-directed**: EvalGlass supplies the machinery, not the metric
set. When the host names a check the app needs, **`authoring-a-metric`** scaffolds it as a
`MetricSpec` across the runtime / reference / judge tiers — the framework derives no metrics on its
own (automated metric discovery is deliberately out of scope; EvalGlass runs the checks the host
authors and infers none itself).

Bare invocation of the umbrella prints an honest status dashboard and runs nothing. A fresh run is
**informational** until the host has earned authority (validated gold, an approved threshold, a
calibrated judge). When reporting any result, the `evalglass-honesty` skill applies — state the
verdict and authority/calibration/comparability state before any number. The plugin ships **no**
verb that gates, approves, certifies, validates, or makes a run "pass" — those belong to the host
and are resolved only by the Verdict Engine.

The same canonical `skills/` tree backs both Claude Code and Codex; runtime-specific packaging
lives in the per-runtime manifests (`.claude-plugin/`, `.codex-plugin/`), never in skill bodies.
The vendored runtime under a host's `evals/_evalglass/` keeps working after the plugin and the
agent are removed.

## Contributing to EvalGlass

If you are working on the EvalGlass **framework itself** (not just using the plugin), read
[`CLAUDE.md`](./CLAUDE.md) first — it is the canonical build guide and the architecture and
trust-model contract. This `AGENTS.md` does not duplicate or override it.
