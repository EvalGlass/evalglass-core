# Security policy

## Reporting a vulnerability

If you have found a security issue in EvalGlass — particularly one that could allow a green scorecard to be misread as proof of correctness (see CLAUDE.md §5, §12) — **please do not open a public issue**.

Use GitHub's [private vulnerability reporting](https://github.com/EvalGlass/evalglass-core/security/advisories/new) to file a private advisory. We will acknowledge within 5 working days.

If GitHub private reporting is unavailable to you, email `contact@evalglass.com` with subject `EvalGlass security`.

## Scope

In scope:

- The EvalGlass runtime (`src/evalglass/**`).
- The scaffolding that the skill writes into host repos.
- CI workflows that consume privileged tokens.

Out of scope (please file a normal issue instead):

- Third-party host code that *uses* EvalGlass.
- Issues in optional adapters that are not enabled by default.

## Supported versions

EvalGlass is pre-alpha. Until a 0.1 release, only `main` is supported. After 0.1, the most recent minor will receive security fixes.

## Coordinated disclosure

We follow a 90-day coordinated disclosure window by default, shorter if a fix is already in production at downstream users.
