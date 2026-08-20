# ADR 0003 — Linter and formatter: ruff + mypy strict

- **Status:** accepted
- **Date:** 2026-05-23

## Context

A static analysis stack for EvalGlass has to satisfy several constraints:

- **Minimal dependency surface.** Each tool we adopt is a thing maintainers must learn, contributors must install, and CI must pin. CLAUDE.md §8 is explicit that we should prefer one tool that covers many concerns.
- **Strict types at boundaries.** The Evaluation Core's contracts are typed boundaries; type errors there are correctness bugs, not style.
- **Fast pre-commit.** A slow lint loop drives contributors to skip hooks.

## Decision

The linting / formatting / typing stack is:

| Concern                  | Tool                  | Notes                                                |
|--------------------------|-----------------------|------------------------------------------------------|
| Lint + format            | `ruff` ≥ 0.7          | Replaces black, isort, flake8, pyupgrade, pylint-lite. |
| Static security          | `ruff` rule family `S` + standalone `bandit` for tools/ | Belt-and-braces; bandit covers things ruff doesn't. |
| Type checking            | `mypy --strict`       | Strict by default. Specific opt-outs via `[[overrides]]`. |
| Documentation style      | `ruff` rule family `D` (off by default for now) | Will be enabled per-package as we add public surface. |
| Typo / spell check       | `codespell` (pre-commit only) | Cheap, opinionated. Not gating. |

Ruff is configured as the canonical formatter (`ruff format`), replacing black.

## Consequences

- One tool reads `pyproject.toml`, so contributors learn one config.
- Pre-commit runs ruff at sub-second speed; mypy runs at pre-push only (still strict in CI).
- We accept a small "convergence risk": ruff's rule coverage is still expanding. The mitigation is that we run mypy strict in CI — the type checker catches what ruff doesn't.

## Alternatives considered

- **black + isort + flake8 + pylint + bandit + mypy.** Rejected — five tools, five configs, slower pre-commit, more dependabot noise.
- **pyright instead of mypy.** Considered. Mypy chosen because its strictness flags are more granular and its error messages are friendlier for the structural contracts we'll write in `core/`. Open to revisiting via a new ADR when concrete types exist.
