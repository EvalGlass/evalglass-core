# EvalGlass plugin release checklist

Gates the first plugin release (`v0.1.0`) and every release after. Decision: ADR 0022 (plugin
packaging & delivery). Nothing here grants authority — it
only checks that the release identity is coherent and the rendered prose does not overclaim.

## Before tagging

- [ ] **Five-way version alignment.** The four in-repo locations agree (enforced by
      `tests/plugin/test_version_alignment.py`): `.claude-plugin/plugin.json` ·
      `pyproject.toml [project].version` · `src/evalglass/__init__.py:__version__` · `CITATION.cff`.
      The **git tag** is the fifth — it must equal them (`vX.Y.Z`). The marketplace entry inherits
      from `plugin.json` (no separate version).
- [ ] **Strict validation** green: `claude plugin validate . --strict` (run on a pinned recent
      Claude Code version).
- [ ] **Honesty audit** green: `pytest tests/plugin/test_honesty_audit.py` — no overclaim in
      README / marketplace / CITATION / bootstrap / skills / plugin-docs / examples; any committed
      demo Scorecard is `informational` or `blocked`.
- [ ] **Manifest consistency**: skills/verbs on disk match what the README and CITATION claim.
- [ ] **Deletion-invariant** green: `pytest tests/plugin/test_first_run_e2e.py` — removing the
      plugin yields a byte-identical `VerdictPayload`.
- [ ] **Full suite + lint + type**: `pytest`, `ruff check`, `ruff format --check`, `mypy` all green.
- [ ] **CHANGELOG.md** has a dated, scoped entry for the version (scope + limitations).

## Badges (scoped, no false confidence)

Every badge must point at a workflow that actually runs the code/validation it claims, or it is
removed. Allowed: License (Apache-2.0), release/version, marketplace-install, "Claude Code Plugin",
Python version, and a **framework-tests** badge wired to the suite that runs in CI. A generic
"tests passing" badge is **not** allowed if its workflow does not exercise the surface it sits above
(plugin skill/command *content* is validated by these `tests/plugin` checks + transcript probes,
which a unit-test badge must not imply).

## GitHub topics

`claude-code`, `claude-code-plugin`, `agent-skills`, `ai-safety`, `llm-eval`, `evaluation`, `ci`,
and intent-anchored `promptfoo`, `deepeval`, `llm-testing`, `llm-as-judge`.

## Tag and release

- [ ] Tag `v0.1.0` only after every box above is checked.
- [ ] GitHub Release notes = the CHANGELOG entry (scope + limitations, incl. `connect --live`
      and synthetic-data generation deferred).

## Marketplace / community submission (after release)

- [ ] Marketplace copy says EvalGlass installs an evaluation framework and **stops for host
      validation before any gate** — no fabricated testimonials, "trusted by" logos, or safety
      claims.
- [ ] Install docs: `/plugin marketplace add EvalGlass/evalglass-core` →
      `/plugin install evalglass-core@evalglass`.
- [ ] Submit to the community marketplace / directories **only** after strict validation,
      honesty audit, manifest consistency, and version alignment are green.
