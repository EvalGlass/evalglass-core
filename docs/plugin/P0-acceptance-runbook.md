# EGP-P0 acceptance runbook

Evidence steps for **EGP-P0 — Claude Code plugin skeleton**. Automated checks run in
`tests/plugin/` + `tools/validate_plugin.sh`; the interactive probes below need a live Claude Code
session and are captured as transcripts (EGP-P0-8). Decision: ADR 0022 (plugin packaging &
delivery).

## Automated (hermetic) — must be green

| Check | Command | Proves | Ticket |
|---|---|---|---|
| Structural floor | `.venv/bin/python -m pytest tests/plugin -q` | manifests valid; vendoring boundary holds; skill frontmatter + no authority verb + honesty guardrail + no overclaim; bootstrap exit-0/state-free; direct CLI intact | P0-2..8 |
| Strict validation | `claude plugin validate . --strict` | the manifests pass Claude Code's own validator (run on a pinned recent version; verified green on 2.1.160) | P0-2, P0-8 |
| Both, one shot | `tools/validate_plugin.sh` | the above together | P0-8 |

## Interactive probes (transcript evidence) — run in a clean Claude Code session

Load the plugin locally with `claude --plugin-dir .` (or install via the marketplace), then capture
a transcript for each:

1. **Invocation token** — type `/evalglass`. *Expect:* the umbrella resolves and prints the honest
   **status dashboard** (integration/data/metric/authority state + next step) and **runs nothing**.
   If the bare-space `/evalglass <verb>` form does not carry free-text verbs, record the namespaced
   fallback actually used and amend ADR 0022 (per plan P0.2).
2. **A routed verb** — type `/evalglass setup` (or `run`, etc.). *Expect:* the umbrella routes to the
   right backing skill and proposes the exact Bash invocation; it does not execute silently.
3. **Natural-language trigger** — say *"evaluate my agentic app with EvalGlass"*. *Expect:* the
   `evaluate-an-agentic-app` skill triggers and routes into the umbrella (no silent file mutation).
4. **SessionStart bootstrap** — start/clear/compact a session. *Expect:* one short pointer line
   ("EvalGlass plugin available… /evalglass…"), no run state, no quality claim; session not blocked.
5. **Honesty guardrail** — ask the agent to summarize any EvalGlass result. *Expect:* it leads with
   verdict/authority state, calls an informational run "informational" (never "passing").
6. **Migration** — confirm `python -m evalglass.installer discover --root .` still works unchanged.

## Exit criterion (EGP-P0)

A clean session installs/validates the plugin, discovers `/evalglass`, triggers the intended route,
and sees only honest display-only bootstrap text — and `python -m evalglass.installer` still works.
