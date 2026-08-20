# ADR 0004 — SonarCloud as informational quality signal

- **Status:** accepted
- **Date:** 2026-05-23

## Context

We use SonarCloud (`Syntelesis-Lab-evalglass`) to track code quality on every PR. CLAUDE.md §5 is uncompromising about authority:

> Only the Verdict Engine may decide CI behavior. ... Unvalidated gold is informational. ... Proposed thresholds are informational.

That applies to *EvalGlass's own outputs*, not to Sonar. But the principle generalizes: a gate that fires without a calibrated, approved threshold is a gate that lies. Sonar's defaults (e.g. "≥ 80% coverage on new code") are reasonable but not calibrated against this codebase, and applying them as hard gates on day one would create exactly the kind of silent false-confidence we are trying to eliminate from the product.

## Decision

- SonarCloud's status is **informational** until we have lived with the project for at least one milestone (M0).
- The `sonar` CI job runs on every PR and the result is surfaced via PR decoration.
- Branch-protection does include the `sonar` job as a required check, but the **quality gate** in SonarCloud is configured to be permissive (no hard thresholds on new-code coverage) for now.
- Tightening the gate is a deliberate decision recorded in a follow-up ADR — not a default we accept silently.

Operationally:

- `pyproject.toml` sets `[tool.coverage.report] fail_under = 0` — coverage is reported, not gated.
- `sonar-project.properties` excludes `tests/**`, `tools/**`, and `__init__.py` from coverage measurement.
- Sonar's `Sonar way` gate is the starting point; we will customize it via the SonarCloud UI once we have at least 1000 lines of core code analysed.

## Consequences

- A PR that lands new untested code will not be auto-blocked by Sonar. The reviewer is responsible for asking why.
- We avoid the worst version of "gate by default and ignore": once a team learns to override a gate, the gate is dead. Better to leave it informational and earn the right to make it gating.
- When we do enable a Sonar gate as authoritative, the threshold becomes a *promise* recorded in an ADR — the same shape of authority we ask hosts to use for their metrics.

## Alternatives considered

- **Sonar "Sonar way" gate as a hard fail.** Rejected — see context.
- **Disable Sonar until we have coverage data.** Rejected — we want the data and the PR decoration; "informational" is the right middle path.
