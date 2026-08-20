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
- **Architecture** — [`../docs/architecture.md`](../docs/architecture.md).
- **Decisions** — [`../adrs/`](../adrs/) (plugin packaging is ADR 0022; Codex second runtime is ADR 0023).

## Status & ownership

The full page-by-page reference lives at [evalglass.com/docs](https://evalglass.com/docs) and is
being re-homed into this directory **incrementally**, page by page (ADR 0022). This index and
[`vocabulary.md`](./vocabulary.md) are the first canonical pages here; until a page is present here,
treat the in-repo concept sources above as authoritative.
