# ADR 0026 — Rename the integration-time package `skill` → `installer`

- **Status:** accepted
- **Date:** 2026-06-02
- **Supersedes:** the naming in ADR 0010 (skill home and shape) — the *home* and *shape* decisions stand; only the package name changes.
- **Reuses:** ADR 0011 (vendoring namespace), ADR 0022 (plugin packaging)

## Context

`src/evalglass/skill/` is the framework's **integration-time installer** — `discover` → `plan` →
`vendor` (copy `core`/`harness`/`adapters` into `evals/_evalglass/` + write `vendor-manifest.json`
/ `evalglass.lock`) → `scaffold` → `revendor`, exposed as `python -m evalglass.skill`. It is **not**
a Claude Code skill: a Claude skill is model-invoked Markdown, and those now live at the plugin root
in `skills/` (ADR 0022). Having a Python package named `skill` sitting next to the plugin's `skills/`
is a legacy artifact of the pre-plugin era ("EvalGlass ships as a single SKILL.md") and is a
permanent source of confusion.

EvalGlass is pre-release (no tags; the plugin is the front door), so renaming the public module now
has **no external-user cost** and is contained entirely to this repo — no host-facing artifact
references `evalglass.skill` (hosts run the vendored `_evalglass.harness.cli`).

## Decision

1. **Rename the package `evalglass.skill` → `evalglass.installer`** (`git mv`, history preserved).
   The public invocation becomes `python -m evalglass.installer …`; the bundled launcher
   (`bin/evalglass-launch`) and every plugin skill that drives it are updated.
2. **Rename the console script** `evalglass-skill` → `evalglass-install`
   (`evalglass.installer.cli:main`).
3. **Rename the error type** `SkillError` → `InstallerError` (the only "skill"-named public symbol).
4. **Delete the legacy `SKILL.md`** that lived inside the package — it was the pre-plugin
   single-skill recipe: undiscovered (Claude loads skills from `skills/`, not `src/`), superseded by
   `skills/installing-evalglass/SKILL.md`, and name-colliding with the umbrella skill `evalglass`.
5. **Rename the test home** `tests/skill/` → `tests/installer/` and the boundary guard
   `tests/core_isolation/test_skill_boundary.py` → `test_installer_boundary.py`.

## Out of scope (deliberately)

- The **abstract role term** "EvalGlass Skill" in `CLAUDE.md`, `docs/architecture*.md`, and the
  build contract — a doctrine/vocabulary label, not a code path. It MAY migrate to "EvalGlass
  Installer" in a later docs pass; leaving it now keeps this slice bounded and reviewable.
- The **EG-M3 / EGTS-M3 "EvalGlass Skill" milestone** identifiers — historical ticket/milestone
  labels (the milestone that built the installer). EGTS suite filenames keep their names; only their
  `evalglass.skill` imports are updated.
- ADR 0010's record is unchanged except a "superseded by 0026 (naming)" note — ADRs are records.

## Consequences

- The direct-CLI path is now `python -m evalglass.installer install --root .` (was
  `python -m evalglass.skill …`). Pre-release, so this is a clean rename, not a break; the migration
  note is updated.
- The vendoring boundary is unchanged: `installer/` is integration-time only and is **never**
  vendored into a host (`MANAGED_PACKAGES = core/harness/adapters`, ADR 0011); the
  runtime-independence guard now asserts no runtime package imports `evalglass.installer`.
- The `skill`/`skills` overload is gone: `skills/` = the plugin's Claude skills;
  `evalglass.installer` = the installer engine they drive.

## Alternatives considered

- **Keep the name, add a docstring.** Rejected: documents the confusion instead of removing it, and
  every future reader still meets a `skill` package that isn't a skill.
- **`integration` / `setup` as the name.** `setup` collides with the `/evalglass setup` verb and
  `setup.py`; `integration` is accurate but longer. `installer` is the clearest noun for the artifact.
- **A deprecation shim (`evalglass.skill` re-exports `evalglass.installer`).** Rejected: unnecessary
  pre-release with no external users; it would re-introduce the name we are removing.
