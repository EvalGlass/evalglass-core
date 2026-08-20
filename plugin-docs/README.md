# `plugin-docs/` — the agent-reference (bundled with the plugin)

The canonical, agent-facing reference the EvalGlass skills cite. It is an integration-time delivery
surface — **never vendored** into a host and never referenced by host evaluation code (ADR 0022).

It is the **shared** reference for both runtimes: the same canonical `skills/` tree (and this
`plugin-docs/`) backs **Claude Code** and **Codex**, which differ only in their thin per-runtime
manifests (`.claude-plugin/` + the `SessionStart` hook; `.codex-plugin/` + `AGENTS.md`). Skill
bodies stay runtime-neutral; runtime-specific packaging lives in the manifests, not here (ADR 0023).

## Canonical concept sources (authoritative, in-repo)

The vocabulary and contracts are defined once, in the framework's own docs; the skills and this
reference point here rather than restating (so nothing drifts):

- **Vocabulary & concepts** — [`vocabulary.md`](./vocabulary.md) (the one-page term index).
- **Design tenets** — [`../docs/design_principles.md`](../docs/design_principles.md).
- **Architecture** — [`../docs/architecture.md`](../docs/architecture.md) and the
  [build contract](../docs/architecture_build_contract.md).
- **Decisions** — [`../adrs/`](../adrs/) (plugin packaging is ADR 0022; Codex second runtime is ADR 0023).

## Status & ownership

The detailed page-by-page reference currently lives in the separate `evalglass-site` repo
(`public/reference`). It migrates into this directory **incrementally**, page by page, with the
site switching to rendering/linking these files as each page lands (ADR 0022). This index
and [`vocabulary.md`](./vocabulary.md) are the first canonical pages here; the remaining reference
pages are tracked and not yet claimed as re-homed. Until a page is here, treat the in-repo concept
sources above as authoritative.
