# EGP-P3 acceptance runbook — Codex second runtime

Evidence for **EGP-P3 — Codex second runtime**. The repo-side packaging, versioning, sync, and
cross-runtime independence are proven by hermetic checks in `tests/plugin/`. The *live* Codex
trigger transcript and the marketplace submission are **maintainer steps** (they need a real Codex
session + the destination fork + the open Codex-fork decision) — they are reported here as **not
exercised**, never as passing. Decision: ADR 0023 (Codex second-runtime packaging).

## Automated (hermetic) — must be green

| Check | Proves | Ticket |
|---|---|---|
| `tests/plugin/test_codex_portability.py` | `.codex-plugin/plugin.json` identity (`name`/`version`/`license` byte-identical to the Claude manifest) + `interface{}` + `skills` path; one canonical, runtime-neutral `skills/` tree; `AGENTS.md` is routing-only and asserts no quality claim | P3-1, P3-2 |
| `tests/plugin/test_version_bump.py` | `.version-bump.json` covers every version surface incl. the Codex manifest; `bump-version.sh --check` fails on drift; `--audit` reports surfaces + the expected `v<version>` tag | P3-3 |
| `tests/plugin/test_sync_codex.py` | `sync-to-codex-plugin.sh --stage` assembles the Codex payload and excludes runtime-specific infra; staged `skills/` are byte-identical to canonical (fidelity); two stages are byte-identical (determinism) | P3-4 |
| `tests/plugin/test_crossruntime_independence.py` | the vendored runtime's typed `VerdictPayload` is byte-identical whether installed by Claude, by Codex, or with neither present; the generated host tree carries no runtime-specific token | P3-5 |
| `tests/plugin/test_honesty_audit.py` | `AGENTS.md` + `.codex-plugin/*.json` prose carry no overclaim | P3-1 |
| full suite + `claude plugin validate . --strict` | no regression; the Claude manifest is still valid alongside the Codex one | — |

## Maintainer steps (not exercised here)

These require a live Codex environment and the destination fork; run them at release time.

1. **Codex acceptance probe (live transcript).** In a clean Codex session with the EvalGlass
   plugin installed, type the trigger phrase *"evaluate my agentic app with EvalGlass"* (or invoke
   the `evalglass` umbrella). *Expect:* the umbrella skill loads and routes; `run --example
   quickstart` (or the host flow, where supported) produces a **populated, informational** Scorecard
   with a diagnostic — narrated as informational, never "passing". Determinism of the sync does
   **not** prove triggering — this transcript does (plan §8.6). Capture it as evidence.
2. **Runtime-after-removal on Codex.** With a Codex-installed host, remove the Codex plugin and
   re-run the vendored `evals/_evalglass/` runtime; confirm the verdict is unchanged. (The hermetic
   `test_crossruntime_independence.py` proves the typed-payload identity; this is the live confirmation.)
3. **Deterministic sync (live).** `scripts/sync-to-codex-plugin.sh --dry-run` to preview, then
   `--fork <ORG/REPO>` (with `gh` authenticated) to open the sync PR to the Codex marketplace fork.
   Run it twice against the same source SHA — the two PRs must have identical diffs.
4. **Version alignment + honesty audit + `--strict` validation** are green (the gates above).
5. **Submission.** Update the README / `plugin-docs` Codex section, then submit to the Codex
   marketplace/directory. **Blocked on Open Question 7** — confirm EvalGlass wants a Codex fork
   and the destination repo before any public submission.

## Exit criterion (EGP-P3)

A Codex user sees the same honest EvalGlass workflow from the same canonical `skills/` tree, with
version/drift gates green and runtime independence proven across runtimes. The repo ships everything
needed to publish; the public Codex listing is a maintainer go/no-go.
