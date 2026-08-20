# ADR 0002 — Package manager: uv

- **Status:** accepted
- **Date:** 2026-05-23

## Context

EvalGlass is a Python library that will be vendored into host repositories. CLAUDE.md §8 is explicit that every dependency is "vendored cost" and that the standard library is preferred. The package manager we choose affects:

- how fast contributors can iterate locally;
- how reproducible our CI is;
- how complex the install instructions are for hosts that integrate via the skill;
- whether we ship a lockfile that hosts can rely on.

## Decision

We use [uv](https://github.com/astral-sh/uv) (≥ 0.9) as the canonical package manager, build runner, and tool runner.

- `pyproject.toml` is the single source of truth for project metadata, runtime deps (empty in M0), and dev-deps (in a `[dependency-groups] dev` table).
- `uv.lock` is committed to the repository.
- CI uses `astral-sh/setup-uv@v5` and `uv sync --frozen`.
- Developers use `uv run <command>` rather than activating a venv manually.

## Consequences

- Single binary, no daemon, no per-machine virtualenv juggling. Matches "boring, inspectable" (CLAUDE.md §8).
- Lockfile-first installs are reproducible across CI and developer machines.
- Hosts integrating EvalGlass via the skill do **not** need uv themselves — the runtime we vendor uses standard `pyproject.toml` metadata. The skill may scaffold whatever the host already uses (`pip`, `poetry`, `uv`).
- The `setup-uv` action is a third-party dependency in CI. We accept it because it is open-source, narrow in scope, and tracks `uv` releases.

## Alternatives considered

- **pip + pip-tools + venv.** Rejected — slower, more moving parts, two-file (requirements.in / requirements.txt) workflow.
- **Poetry.** Rejected — heavier, slower to install, and its lockfile format is less ergonomic for re-vendoring into host repos.
- **Hatch.** Considered. We use the Hatchling *build backend* (line in `[build-system]`) but not Hatch the environment manager — uv is faster.
