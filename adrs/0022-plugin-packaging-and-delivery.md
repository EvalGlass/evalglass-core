# ADR 0022 — Claude Code plugin packaging and delivery boundary

- **Status:** accepted
- **Date:** 2026-06-02
- **Reuses:** ADR 0010 (skill home / runtime independence), ADR 0011 (vendoring namespace), ADR 0012 (`vendor-manifest.json` / `evalglass.lock`)
- **Source:** `docs/PLUGIN_TRANSFORMATION_PLAN.md` v4 (§2, §4, §5, §6, §9, §10)

## Context

EvalGlass shipped originally as a single integration-time skill (a `SKILL.md` recipe over the
`evalglass.installer` engine; the recipe later re-homed into `skills/installing-evalglass/`, ADR 0026).
Its real agent-facing surface is plugin-sized — discover → connect → run → view → explain →
compare → wire CI, plus an authoring tier — and it wants marketplace discoverability. The
transformation plan (the P-series packaging design, kept as a local working doc) repackages the
**delivery layer** as a Claude Code plugin (Codex as a second runtime) **without changing the evaluation
framework**. This ADR records the packaging decision and its boundaries so implementation
tickets do not depend on conversation memory.

## Decision

1. **Delivery/packaging only.** The plugin is a new *delivery* surface. It freezes the
   Evaluation Core (effect-free, stdlib-only), the single Verdict Engine, the vendoring
   boundary (`evals/_evalglass/`), typed authority, host-owned truth, and the
   no-false-confidence doctrine. The plugin **adds zero imports** to the core and introduces
   no second verdict path. Per the plan's central rule: *the plugin is a typist and a reader,
   never a participant in the evaluation — it asks; the host validates; the runtime decides.*

2. **Home & distribution.** The plugin lives at the **framework repo root** as a
   **single-plugin marketplace** (`.claude-plugin/marketplace.json` with `source: "./"`), one
   version line across `plugin.json` · `pyproject.toml` · `src/evalglass/__init__.py:__version__`
   · `CITATION.cff` · git tag. Plugin component directories (`skills/`, `commands/`, `hooks/`,
   `plugin-docs/`, `assets/`, `bin/`, `.claude-plugin/`) are **additive and orthogonal** to
   `src/evalglass/` and are **never vendored** into a host — vendoring copies only
   `core`/`harness`/`adapters` (ADR 0011, `MANAGED_PACKAGES`). This preserves
   runtime-after-removal by construction.

3. **Skill-based umbrella, no authority verbs.** The user surface is one `/evalglass <verb>`
   umbrella realized as a **skill named `evalglass`** (the proven claude-seo pattern; not a
   command file), plus one always-on `evalglass-honesty` narration guardrail, one
   natural-language router, the backing skills, and **one** display-only `SessionStart` hook.
   The plugin ships **no** `gate` / `approve` / `certify` / `pass` / `verify` / `validate` /
   `score`-activation verb — the absence is the identity. No MCP server; no `PostToolUse` hook
   in v1.

4. **Two invocation targets, kept distinct.** Integration-time acts (discover/plan/install/
   upgrade) run the **bundled** framework from `${CLAUDE_PLUGIN_ROOT}` (a marketplace-only user
   has not `pip install`ed the framework); host evaluation runs the host's **vendored**
   `_evalglass` (`PYTHONPATH=evals python -m _evalglass.harness.cli …`), never the framework
   package, never via import. The direct `python -m evalglass.installer …` path is unchanged.

5. **Sequencing.** `v1` ships the core verbs; the authoring tier and `connect --live` are
   `v1.1`; Codex is `P3`. **F1** (adding `example_id`/`unit_id` subject identity to `Score` to
   enable `view --by-call`) is a deferred, ADR-governed *framework* follow-up that **does not
   block plugin v1**; per-source-function views remain an advanced extension.

## Consequences

- The framework milestones M0–M5 are untouched; the plugin work is tracked as a distinct
  **P0–P3** packaging series (see `docs/IMPLEMENTATION_PLAN.md`).
- Removing the plugin (and the agent) must leave every host verdict byte-identical — enforced
  by the deletion-invariant gate (plan §5) layered on the existing runtime-independence proof
  (`tests/skill/test_runtime_independence.py`, EGTS-M3-4).
- `view --by-call` cannot ship until F1 lands and a test proves `Score` carries its subject;
  v1 `view` is per-metric.
- Plugin prose (manifests, skills, bootstrap) is subject to a fail-closed honesty audit so the
  delivery layer cannot overclaim any more than a Scorecard can.

## Alternatives considered

- **A separate plugin repo.** Rejected: it would fork the skill content the framework already
  owns (ADR 0010) and split the version line, creating the drift the manifest-consistency gate
  exists to prevent.
- **Command-file umbrella (`commands/evalglass.md`).** Deferred to a documented fallback: the
  exact `/evalglass <verb>` invocation token is proven in P0 (EGP-P0-8); the skill-based
  umbrella is the verified-safe primary (claude-seo ships `/seo` as a skill with no `commands/`).
- **An MCP server for result queries.** Declined for v1: a long-lived server risks becoming a
  runtime dependency, violating P13 / ADR 0010.
