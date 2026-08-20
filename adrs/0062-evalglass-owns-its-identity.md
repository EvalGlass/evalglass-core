# ADR 0062 — EvalGlass owns its identity: marketplace `evalglass`, plugin `evalglass-core`

- **Status:** accepted
- **Date:** 2026-08-08
- **Supersedes:** [ADR 0027](0027-marketplace-named-after-publisher.md) (which named the marketplace after the previous umbrella org)

## Context

The project moved to its own GitHub organization, `EvalGlass`, and the repository was renamed
`evalglass-core` (`github.com/EvalGlass/evalglass-core`). EvalGlass now owns its own identity: the
publisher, catalog, and copyright are **EvalGlass**, not the umbrella lab that incubated it.

ADR 0027 chose the marketplace name to match the publisher's GitHub org slug, and kept the plugin
name distinct so the install command would not read as a redundant `evalglass@evalglass`. That
reasoning still holds — only the publisher org has changed.

## Decision

Name the marketplace after the new publisher org slug, and rename the plugin to match the repo, so
the two install tokens stay distinct:

```text
/plugin marketplace add EvalGlass/evalglass-core   # repo slug
/plugin install evalglass-core@evalglass           # plugin `evalglass-core` from marketplace `evalglass`
```

- `.claude-plugin/marketplace.json` `name`: `syntelesis-lab` → `evalglass` (the org's one catalog,
  into which future plugins can be listed).
- `.claude-plugin/marketplace.json` `plugins[0].name`, `.claude-plugin/plugin.json` `name`, and the
  `.codex-plugin` manifest `name`: `evalglass` → `evalglass-core`, matching the repo.
- `owner` / `author` / copyright become **EvalGlass** (`contact@evalglass.com`,
  `github.com/EvalGlass`). One "Built by Syntelesis Lab" credit remains at the foot of the README.
- The Python package, console script, provenance string (`evalglass@<version>`), and the
  `/evalglass` umbrella skill keep the name `evalglass` — the product name is unchanged; only the
  plugin / marketplace / publisher identity moved.

## Consequences

- `plugin != marketplace` still holds (`evalglass-core` vs `evalglass`), so the ADR 0027 install
  invariant in `tests/plugin/test_manifests.py` is preserved with the new values.
- Install-surface only; nothing vendored into a host or in generated CI references these names, and
  EvalGlass is pre-release, so the rename has no external-user cost.
- SonarCloud remains under the previous organization (`syntelesis-lab`, project
  `Syntelesis-Lab-evalglass`) until a new SonarCloud org bound to `EvalGlass` is created and the
  `SONAR_TOKEN` secret rotated. Until then, `sonar-project.properties` and the two ADRs that cite
  the Sonar project key keep the old identifiers; this is the one external dependency the identity
  move cannot resolve from inside the repo.

## Alternatives considered

- **Keep `syntelesis-lab`** as the marketplace name. Rejected: the project is no longer published
  under that org; the catalog should carry the owner's identity.
- **Name the marketplace `evalglass` and keep the plugin `evalglass`** (`evalglass@evalglass`).
  Rejected for the same duplication reason ADR 0027 gave; renaming the plugin to `evalglass-core`
  (the repo name) keeps the two tokens distinct.
