# ADR 0001 — Architecture boundary: Evaluation Core / Runtime Harness / Skill

- **Status:** accepted
- **Date:** 2026-05-23

## Context

EvalGlass is an instrument. Its outputs are only useful if they can be trusted, and trust is structural — it has to survive code that touches files, calls LLMs, looks at the clock, or imports vendor SDKs. If those effects are mixed into the same module as the logic that decides whether a run passes or fails, then no amount of testing can rule out the case where a result depends on hidden state.

CLAUDE.md §4 already codifies the boundary in prose. This ADR makes the choice explicit, so future contributors understand that the separation is load-bearing — not stylistic.

## Decision

EvalGlass is split into three layers, with strict directional dependencies:

1. **Evaluation Core** (`src/evalglass/core/**`) — effect-free. No file I/O, no network, no LLM calls, no vendor SDK imports, no environment reads, no wall-clock time, no randomness, no host code execution.
2. **Runtime Harness** (`src/evalglass/harness/**`) — effectful orchestration. Effects must be visible, testable, and behind ports.
3. **Adapters** (`src/evalglass/adapters/**`) — concrete implementations of ports. Vendor SDK imports live here, never in the core.

The **Skill** (delivered separately as a Claude Code / Codex skill) is integration-time only: it scaffolds the runtime into a host repo. Once installed, the vendored runtime must work without the skill or any coding agent.

## Enforcement

- Structural: `tools/check_core_isolation.py` walks `src/evalglass/core/**` with the AST and refuses forbidden imports, attribute accesses on `sys.*`, and a small set of forbidden builtins (`open`, `input`, `exec`, `eval`).
- The same gate runs as a pytest test (`tests/core_isolation/`) and as a pre-commit hook, so the diagnostic shows up wherever someone is working.
- A CI job named `core-isolation` is a required status check (Phase 1).

## Consequences

- The Verdict Engine — the only component allowed to emit `pass / fail / blocked / informational` — lives in the core. Its inputs are pure data structures; its output is one of four literal verdicts.
- Adding a feature to the core that would need I/O is a sign that the feature belongs in the harness or an adapter, not the core. Reviewers should push back rather than accept.
- We accept a small ergonomics tax: helpers that read fixtures, parse environment, or call wall-clock have to live outside the core, even if they feel "core-adjacent."

## Alternatives considered

- **One package, convention-only.** Rejected — convention erodes; structural checks do not.
- **Per-file annotations (`# core-pure: true`).** Rejected — overheads of metadata maintenance outweigh the benefit of having a single import-rule.
