# ADR 0027 — Name the marketplace after the publisher (`syntelesis-lab`), not the plugin

- **Status:** superseded by [ADR 0062](0062-evalglass-owns-its-identity.md) — the project moved to its own `EvalGlass` org; the marketplace is now `evalglass` and the plugin `evalglass-core`. This record is kept for history.
- **Date:** 2026-06-02
- **Supersedes:** Open Question 10 in `docs/PLUGIN_TRANSFORMATION_PLAN.md` (which set the marketplace name *identical* to the plugin name); refines ADR 0022 §2 (home & distribution).
- **Source:** `code.claude.com/docs/en/plugin-marketplaces` (verified 2026-06-02)

## Context

Install is `/plugin install <plugin>@<marketplace>` (plugin first, marketplace after `@`). The
original decision (OQ10) made the marketplace `name` *identical* to the plugin `name` "for
memorability", yielding `/plugin install evalglass@evalglass`.

Two problems:

1. **It reads as a redundant duplication** — `evalglass@evalglass` obscures which token is the
   plugin and which is the marketplace.
2. **It misuses the marketplace.** Per the official docs, a marketplace `name` is a *publisher's
   catalog* identifier (their examples: `acme-tools`, `company-tools`, `my-plugins`), and "to
   publish multiple plugins, list them all under one marketplace name." Naming the catalog after a
   single product makes a second plugin awkward forever.

EvalGlass is pre-release (untagged `0.1.0`, the plugin is the front door), so changing the
install-surface name now has **no external-user cost**.

## Decision

**Name the marketplace `syntelesis-lab`** (the publisher, matching the GitHub org slug
`Syntelesis-Lab`). The plugin stays `evalglass`. Therefore:

```text
/plugin marketplace add Syntelesis-Lab/evalglass     # repo slug (unchanged — that's the repo)
/plugin install evalglass@syntelesis-lab             # plugin `evalglass` from marketplace `syntelesis-lab`
```

- `.claude-plugin/marketplace.json` `name`: `evalglass` → `syntelesis-lab` (kebab; the publisher's
  one catalog, into which future plugins can be listed). `plugins[0].name` stays `evalglass`;
  `owner` stays Syntelesis Lab.
- The plugin name, version surfaces, vendoring boundary, and the `.codex-plugin` manifest are
  **unchanged** — this is an install-surface naming change only.

## Consequences

- The install command no longer duplicates a name; `evalglass@syntelesis-lab` reads as "the
  evalglass plugin from the syntelesis-lab catalog".
- Future Syntelesis Lab plugins can be added to the same `syntelesis-lab` marketplace.
- No host-facing impact — the marketplace name is install-time only; nothing vendored into a host
  or in generated CI references it. `marketplace add` still uses the repo slug.
- The `test_two_namespace_identity` invariant flips from "names are identical" to "plugin and
  marketplace names are deliberately distinct".

## Alternatives considered

- **Keep `evalglass@evalglass`** (OQ10). Rejected: the duplication is the smell this ADR fixes, and
  a product-named catalog does not scale to multiple plugins.
- **`syntelesis`** (short brand, matches the domain). Reasonable, but `syntelesis-lab` matches the
  GitHub org slug exactly, so `marketplace add Syntelesis-Lab/...` and `@syntelesis-lab` line up.
