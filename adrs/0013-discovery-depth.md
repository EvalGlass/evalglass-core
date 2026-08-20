# ADR 0013 — Host discovery depth

- **Status:** accepted
- **Date:** 2026-05-31

## Context

The skill's first step inspects a host repo to propose an honest evaluation setup
(EG-M3-1). Discovery must be conservative and **read-only** — it proposes, it does not
mutate — and it must not require running or importing host code (which would be an effect
and a trust hazard). How deep should it go? Full semantic analysis (LibCST, tree-sitter,
type inference) is tempting for finding LLM call sites, but it adds heavy dependencies and
complexity for a step whose output is only *proposed*.

## Decision

M3 discovery uses **stdlib-only, read-only** techniques:

- **Globs** for repo shape, existing `evals/` assets, recorded traces, and CI configs.
- **Ignore-file handling** (`.gitignore`, including path-qualified directory patterns) so
  ignored trees (`.venv/`, generated dirs) are not scanned.
- **Python `ast`** over *source text* to surface likely LLM call sites — it parses, never
  imports or executes host code or any provider SDK; an unparseable host file is skipped,
  not a discovery failure.
- Unknown data boundaries (recorded sources with no declared policy) become
  `DataPolicyPrompt`s — surfaced as questions, never assumed `permitted`.

LibCST (formatting-preserving edits) and tree-sitter (cross-language discovery) are
**deferred** to a later milestone if/when discovery needs to *edit* host code or support
non-Python hosts.

## Consequences

- No heavy parsing dependency enters the skill; discovery stays fast, hermetic, and safe.
- Call-site hints are heuristic and Python-only — acceptable because they are *proposed*
  for human review, not authoritative.
- Cross-language hosts surface a blocker (unsupported language), not a wrong guess.

## Alternatives considered

- **LibCST / tree-sitter now.** Rejected for M3 — heavy dependencies for output that is
  only proposed; revisit when discovery must edit host code or go cross-language.
- **Import the host package to find call sites.** Rejected — importing host code is an
  effect and a trust hazard (arbitrary code execution at integration time).
