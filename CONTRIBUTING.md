# Contributing to EvalGlass

Thanks for being here. Before submitting a PR, please read [`CLAUDE.md`](./CLAUDE.md) — it is the operating guide for everyone (humans and coding agents alike).

## Quick start

```bash
# 1. Clone
git clone git@github.com:EvalGlass/evalglass-core.git
cd evalglass

# 2. Install uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Sync the project (creates .venv, installs dev deps)
uv sync

# 4. Install pre-commit hooks
uv run pre-commit install --install-hooks
```

## Working locally

```bash
uv run pytest                                    # run the fast suite
uv run pytest -m core_isolation                  # just the structural gates
uv run pytest --cov --cov-report=term-missing    # with coverage
uv run ruff check . --fix                        # lint + autofix
uv run ruff format .                             # format
uv run mypy                                      # strict types
uv run python tools/check_core_isolation.py      # core isolation gate (also runs in CI)
uv run bandit -c pyproject.toml -r src tools     # security
```

## Architectural rules you must respect

These come from `CLAUDE.md` and are mechanically enforced:

1. **The Evaluation Core (`src/evalglass/core/**`) is effect-free.** No file I/O, no network, no LLM calls, no vendor SDKs, no clock, no randomness, no environment reads. Run `tools/check_core_isolation.py` locally to see what the CI gate sees.
2. **Only the Verdict Engine emits verdicts.** Do not duplicate verdict logic in adapters, the CLI, the report generator, or the skill.
3. **No silent gating.** A PR that introduces a check that can fail the build must say what threshold it gates on and where that threshold is recorded.
4. **No domain knowledge in the core.** Anything host-specific belongs in `evals/evaluators/` of the host repo, not here.
5. **Every dependency is vendored cost.** Adding a runtime dependency requires an ADR (see [`adrs/`](./adrs/)). Dev dependencies are softer but still surfaceable in PR description.

## Test families

The CI matrix maps to the test families CLAUDE.md §17 (Testing Expectations) requires. When you add a test, mark it with the right pytest marker so the right CI lane picks it up:

| Marker                  | Family                                                  |
|-------------------------|---------------------------------------------------------|
| `core_isolation`        | Structural checks on the effect-free core               |
| `verdict_matrix`        | Authority-state → verdict mapping coverage              |
| `public_surface`        | CLI / report JSON / schema snapshots                    |
| `adapter_conformance`   | Port/adapter contract tests                             |
| `fixture_e2e`           | Local-runner end-to-end on fixtures                     |
| `ontology`              | Companion-ontology drift guard over `docs/design/ontology` data |
| `live_lane`             | Opt-in optional-lane smoke tests (excluded from required CI) |
| `slow`                  | Tests > 1s (excluded from fast pre-push suite)          |

## Continuous integration & required checks

Every pull request to `main` runs the full quality gate. These checks are **required by branch protection** — `main` cannot be merged into until they pass, the branch is up to date, and review conversations are resolved. `main` is linear-history-only, with no direct pushes, force-pushes, or deletions; all changes land through a PR.

**Static analysis & tests** ([`ci.yml`](./.github/workflows/ci.yml)), aggregated behind the single required **`all required checks`** status:

| Check | Tool |
|-------|------|
| lint | Ruff (`ruff check` + `ruff format --check`) |
| typecheck | mypy `--strict` (product **and** both gate skills) |
| core isolation | `tools/check_core_isolation.py` — the effect-free-core guard |
| security (static) | Bandit |
| tests | pytest on **Python 3.12 and 3.13**, with coverage |
| docs consistency | ontology / status / public-surface snapshots |
| skill tests | the scan-gate and validator-gate suites |
| SonarCloud | code-quality scan — **informational** ([ADR 0004](./adrs/0004-sonarcloud-informational.md)); skips cleanly until `SONAR_TOKEN` is configured |

**Supply-chain & secret scanning** (standalone required workflows):

| Check | Tool |
|-------|------|
| `TruffleHog (verified secrets only)` | [secret scan](./.github/workflows/secret-scan.yml) — verified-only; the false-positive-prone `lob` detector is excluded |
| `Trivy fs` | filesystem vulnerability scan |
| `pip-audit (declared deps)` | dependency CVE audit |
| `licensecheck (declared deps)` | dependency-license policy |

The **`live lanes`** job is opt-in (manual `workflow_dispatch` only) and never gates a PR. Code ownership is enforced through [`CODEOWNERS`](./.github/CODEOWNERS): the architectural seams (core, Verdict Engine, isolation gate, CI config) require `@EvalGlass/maintainers` review.

## Required secrets

CI requires the following repository secrets to be set:

- `SONAR_TOKEN` — SonarCloud project token (Settings → Secrets and variables → Actions). Without it, the `sonar` job is skipped (warning, not failure) and SonarCloud stays informational.

No other third-party secrets are required — the framework is local-first and the required test tier makes no network calls.

## Pull requests

- Use the PR template. The trust-model checklist is not optional.
- One logical change per PR — the per-slice discipline (CLAUDE.md §23): a bug fix doesn't need cleanup; a one-shot operation doesn't need a helper.
- The default merge style is **squash**. Keep commit titles imperative.

## Releases

Pre-release (`v0.1.0`, pre-alpha). The plugin release gates — version alignment, strict manifest validation, the honesty audit, and the deletion-invariant — are tracked in [`docs/plugin/RELEASE_CHECKLIST.md`](./docs/plugin/RELEASE_CHECKLIST.md). Tagging and any PyPI/marketplace publishing are deliberate maintainer steps, not automated yet.
