# ADR 0010 — EvalGlass Skill home and shape

- **Status:** accepted; **naming superseded by [ADR 0026](0026-rename-skill-package-to-installer.md)** — the package was renamed `evalglass.skill` → `evalglass.installer` and the bundled `SKILL.md` recipe was removed (its recipe now lives in the plugin's `skills/installing-evalglass/`). The home/shape decisions below otherwise stand; read `skill` → `installer`.
- **Date:** 2026-05-31

## Context

M3 builds the integration-time EvalGlass Skill: conservative host discovery,
install planning, vendoring, `vendor-manifest.json` / `evalglass.lock`, host-owned
scaffolding, first-run wiring, and re-vendoring (build contract §3/§4/§12;
architecture §8). It has three hard constraints:

1. **Hermetically testable.** EGTS-M3 must drive the skill's mechanical steps
   against fixture host repos and check typed artifacts — so those steps must be
   deterministic Python, not agent judgment (`tests/CLAUDE.md §6`).
2. **Delivered as a Claude Code / Codex skill** (P13): a `SKILL.md` recipe a host's
   coding agent runs, carrying the AI-safety expertise and the human-validation
   checklist the host lacks.
3. **Never a runtime dependency** (P13 boundary): once installed, the vendored
   runtime runs with the skill and agent gone.

The question is where the skill lives in the framework repo: a Python package
under `src/evalglass/`, or a `.claude/skills/` agent skill alongside the dev gates
(scan-gate, validator-gate)?

## Decision

The **engine is a Python package at `src/evalglass/installer/`** (deterministic,
fail-closed contracts mirroring the core; subcommands `discover|plan|install|
revendor` via `evalglass-install` / `python -m evalglass.installer`). The **agent recipe
was a `SKILL.md` packaged alongside it** (removed in ADR 0026 — the recipe now lives in the
plugin's `skills/installing-evalglass/SKILL.md`).

| Force | Resolution |
|---|---|
| Architecture §10 framework-repo shape | Explicitly lists `src/evalglass/installer/`; vendoring boundaries are a `CLAUDE.md §1` protect-first item. |
| CI coverage | `src/**` gets mypy/bandit/ruff/pytest by default; `.claude/**` is excluded and needs the special job (#31). A product surface must be first-class CI. |
| EGTS imports product surfaces | `import evalglass.installer` mirrors `evalglass.core` / `evalglass.harness` (`tests/CLAUDE.md §6` names the skill a public surface). |
| Co-location | The engine reads `src/evalglass/{core,harness,adapters}` to vendor them; locating siblings via package introspection is version-locked. |
| Layer vocabulary | `CLAUDE.md §6` already names "skill code" as a peer layer the core must not import → `evalglass.installer` is a package, enforced by a new import-boundary test. |
| `.claude/skills/` category | scan-gate / validator-gate are dev-gate tooling for *building* EvalGlass — a different category from the shipped product skill. |

Two consequences fall out:

- The skill is **never vendored into a host** — the §10/§11 host layout has no
  `skill/`; vendoring enumerates only `core/harness/adapters`.
- `core`, `harness`, and `adapters` **never import `evalglass.installer`**, enforced by
  an import-boundary test beside `tests/core_isolation/test_core_imports.py` (plus
  scan-gate `imports_effects`). The vendored runtime is standalone by construction.

Host-side distribution places the recipe in the *host's* `.claude/skills/` (or a
marketplace) at integration time; an optional thin `.claude/skills/evalglass/`
pointer in this repo only dogfoods the install.

## Consequences

- Standard CI proves the skill like any other product code; EGTS imports it as a
  product surface and drives it against fixture host repos.
- The "runtime-independent after skill removal" invariant has a structural backstop
  (the import-boundary test) in addition to the EGTS-M3-4 clean-subprocess proof.
- A small amount of agent judgment (reading LLM call sites, resolving a
  `DataPolicyPrompt`) stays in the `SKILL.md` recipe; the deterministic mechanics
  stay in the engine where EGTS can check them.

## Alternatives considered

- **`.claude/skills/evalglass/` (agent skill alongside the dev gates).** Rejected:
  CI excludes `.claude/**` (a product surface must be first-class CI), it conflates
  the product skill with build tooling, and EGTS would not import it as it imports
  the other product surfaces. "That is where Claude Code finds skills" is a
  *host-side distribution* concern, not where the framework authors the recipe.
- **A separately published installer package** (`pip install evalglass-install`).
  Out of scope for M3 and orthogonal to the home decision; the engine can still be
  invoked from a clone or an installed tool without changing its location.
