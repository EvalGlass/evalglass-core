# ADR 0023 — Codex second-runtime packaging

- **Status:** accepted
- **Date:** 2026-06-02
- **Reuses:** ADR 0022 (plugin packaging & delivery boundary), ADR 0010 (skill home / runtime independence), ADR 0011 (vendoring namespace)
- **Source:** `docs/PLUGIN_TRANSFORMATION_PLAN.md` v4 (§8, §10 P3); `docs/plugin_transformation_jira_tickets.xlsx` (EGP-P3); template `obra/superpowers`

## Context

ADR 0022 packaged EvalGlass as a Claude Code plugin. The plan's §8 adds **Codex** as a second
runtime from the **same repo and the same canonical `skills/` tree**, using the `obra/superpowers`
multi-runtime pattern (one skills source, thin per-runtime manifests, deterministic sync-out).

Translating that template to EvalGlass surfaced three decisions the plan did not fully specify,
because superpowers' repo root *is* the plugin (its `CLAUDE.md` and `AGENTS.md` are identical
contributor guides), whereas **EvalGlass's root `CLAUDE.md` is the framework build guide**, not a
plugin bootstrap. Recording them here so implementation tickets do not depend on conversation
memory (CLAUDE.md §1, §18).

## Decision

1. **The Codex trigger/routing surface is `.codex-plugin/plugin.json`.** It carries the richer
   `interface{}` block Codex renders (`displayName`, short/long description, `category`,
   `capabilities`, `defaultPrompt`) and `skills: "./skills/"`. Its `name`, `version`, and
   `license` are **byte-identical** to `.claude-plugin/plugin.json` (one repo, one identity, one
   version line — ADR 0022 §2). The `interface` prose is in honesty-audit scope.

2. **Root `AGENTS.md` is the Codex-runtime entry, not a second build guide.** Unlike superpowers,
   EvalGlass's `CLAUDE.md` is the canonical build/architecture/trust-model contract. So `AGENTS.md`
   is kept **display-and-routing only** (parallel to the Claude `SessionStart` bootstrap): it
   points at the `evalglass` umbrella skill and the entry phrase, keeps the informational-by-default
   framing, asserts no quality/capability claim and reads no run state, and **defers to `CLAUDE.md`**
   for the build guide. It does not duplicate or override it — avoiding a divergent second guide.

3. **The Codex plugin is skills-only.** Canonical Codex plugins ship `skills/` (+ the manifest);
   the sync deliberately excludes `src/`, `bin/`, `hooks/`, `commands/`, `.claude-plugin/`, dev
   gates, and root ceremony files. Consequently a Codex install has **no bundled launcher**: its
   integration-time path is the always-portable direct CLI `python -m evalglass.installer …` (the
   `evalglass` package importable), which every skill already documents alongside the Claude-only
   `${CLAUDE_PLUGIN_ROOT}` launcher. Host evaluation on either runtime uses the host's **vendored**
   `_evalglass` (ADR 0011) and is identical across runtimes.

4. **One canonical, portable `skills/` tree — no per-runtime forks.** Skill frontmatter is
   runtime-neutral (`name`/`description`, plus optional Claude Code UX hints —
   `user-invocable`/`argument-hint` — that other runtimes ignore); skill bodies carry no
   runtime-specific packaging internals (manifests, hooks, `interface{}`); and any skill naming a
   runtime-specific
   `*_PLUGIN_ROOT` variable also offers the portable direct CLI so a non-Claude runtime has a
   working invocation. A drift self-check (the sync script) keeps the synced Codex copy
   byte-identical to the canonical source.

5. **Version surfaces grow by one.** `.codex-plugin/plugin.json:version` joins the alignment set
   (now `plugin.json` · `pyproject.toml` · `__init__.__version__` · `CITATION.cff` ·
   `.codex-plugin/plugin.json` · git tag), enforced by the version-alignment test and the
   `.version-bump.json` audit (EGP-P3-3).

## Consequences

- The framework spine (M0–M5), the single Verdict Engine, typed authority, the vendoring boundary,
  and the no-false-confidence doctrine are **untouched** — P3 is delivery/packaging only.
- Runtime-after-removal holds **across runtimes**: the deletion-invariant verdict-identity proof is
  extended to a Codex-installed workflow (EGP-P3-5).
- **Maintainer go/no-go, gated on Open Question 7** (does Syntelesis Lab want a Codex fork): the
  live Codex acceptance-probe **transcript** (a clean Codex session must actually trigger the
  umbrella skill — determinism of the sync does not prove triggering, plan §8.6), the real
  marketplace submission, and the cross-repo sync **PR** to the Codex marketplace destination. The
  repo ships the deterministic sync script, the drift check, the acceptance-probe **runbook**, and
  the cross-runtime docs; the outward actions are not performed here and are reported *not
  exercised*, never as passing — consistent with the demo-GIF discipline in the P2 build.

## Alternatives considered

- **Root `AGENTS.md` as a full contributor guide mirroring `CLAUDE.md`** (the superpowers habit).
  Rejected: it would duplicate a 600-line build guide and create exactly the drift the
  manifest-consistency discipline exists to prevent; EvalGlass already has one canonical guide.
- **A root `AGENTS.md` that is trigger-only and ignores the build-guide role.** Rejected: Codex
  contributors read root `AGENTS.md`; leaving them only a trigger blurb would hide the real build
  contract. The accepted form is trigger/routing-first **and** points to `CLAUDE.md`.
- **Bundling `src/` into the Codex plugin** so Codex gets a launcher too. Deferred: non-canonical
  for Codex plugins and larger; the portable direct CLI already covers integration-time on Codex.
