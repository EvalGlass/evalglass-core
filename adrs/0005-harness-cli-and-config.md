# ADR 0005 — Runtime Harness CLI and config boundary: argparse + PyYAML

- **Status:** accepted
- **Date:** 2026-05-29

## Context

M1 introduces the Runtime Harness: the local entrypoint that loads host-owned
config, builds core inputs, and renders outputs (architecture.md §7; build
contract §8). Two boundary decisions need recording before code lands, because
they introduce the framework's *first runtime dependency* and the first
user-facing surface:

- **CLI framework.** The harness needs a command surface (`evalglass run …`).
- **Config format.** `evalglass.yaml` is named in the host layout (build contract
  §11); something must parse it.

Constraints: minimal dependency surface (CLAUDE.md §8), predictability over
configurability (design principle P13), the core stays stdlib-only and
dependency-free, and no provider/vendor SDKs on required paths.

## Decision

| Concern | Choice | Notes |
|---|---|---|
| CLI | `argparse` (stdlib) | Zero dependency; predictable, conventional. Typer/Click rejected — a dependency for ergonomics the harness does not need. |
| Config parse | `PyYAML` ≥ 6.0, `yaml.safe_load` **only** | M1's first and (for now) only runtime dependency. `safe_load` never constructs arbitrary objects. |
| Exit codes | `0` pass/informational · `1` fail/blocked · `2` setup/infrastructure error | Setup errors are a distinct class, never a fabricated quality verdict (build contract §8). Slice 1 uses `0`/`2`; `1` activates with the verdict-driven run in EG-M1-5. M2 layers CI annotations on top. |
| Config effects | isolated in `harness/loader.py` | `config.py` is pure typed dataclasses + fail-closed `from_mapping`; only the loader touches the filesystem and YAML. |

PyYAML ships no type stubs. We use a per-line `import yaml  # type: ignore[import-untyped]`
at the single import site — matching the existing repo convention (the EGTS files
already do this) — rather than a global `types-PyYAML` (which has bled into sibling
per-skill mypy jobs) or a project-wide mypy override (which would make those existing
per-line ignores redundant under `warn_unused_ignores`).

## Consequences

- The Evaluation Core remains stdlib-only and dependency-free; PyYAML lives only
  behind the harness config boundary and is recorded in `uv.lock`.
- `evalglass` is exposed as a console script (`[project.scripts]`).
- Config problems surface as typed setup diagnostics with a dedicated exit class,
  never as a low score or a crash.

## Alternatives considered

- **Typer / Click.** Rejected — a dependency (and, for Typer, a Pydantic-adjacent
  surface) bought only nicer help text. argparse is sufficient and stdlib.
- **JSON / TOML config.** Rejected — `evalglass.yaml` is the documented host
  contract; YAML is the most ergonomic for hand-authored host-owned truth.
- **types-PyYAML in dev deps / a global mypy override for `yaml`.** Rejected —
  global stubs previously affected per-skill mypy jobs, and a project-wide override
  would make the EGTS files' existing per-line `import yaml` ignores redundant. A
  per-line ignore at the one import site keeps the type surface minimal and matches
  convention.
