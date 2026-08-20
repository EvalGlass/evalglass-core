# EGP-P1 acceptance runbook

Evidence for **EGP-P1 — core verbs + first-run journey**. Automated checks run in `tests/plugin/`;
the interactive journey is captured as transcripts in a live Claude Code session. Decision:
ADR 0022 (plugin packaging & delivery).

## Automated (hermetic) — must be green

| Check | Proves | Ticket |
|---|---|---|
| `tests/plugin/test_launcher.py` | the bundled launcher runs the bundled skill, self-locates the plugin root, forwards args, and fails closed (exit 2) on a missing framework | P1-1 |
| `tests/plugin/test_verbs.py` | the umbrella routes host `run` to the vendored `_evalglass` (never the framework), `setup` via the launcher, `connect` to import-only (live deferred), `view --by-call` ships (F1 landed), grouping by subject identity, `ci` to a no-plugin scaffold copy | P1-2..10 |
| `tests/plugin/test_first_run_e2e.py` | a vendored first run is populated + **informational** with real non-reference signal; the generated host tree references no plugin/launcher; **deletion-invariant**: the typed `VerdictPayload` is byte-identical with and without the plugin/framework on the path | P1-6, P1-11, P1-12 |
| full suite + `claude plugin validate . --strict` | no regression; manifests still valid | — |

## Interactive probes (transcript evidence) — live Claude Code session

1. **Two-command install + quickstart** — `/plugin marketplace add EvalGlass/evalglass-core` →
   `/plugin install evalglass-core@evalglass` → `/evalglass run --example quickstart`. *Expect:* a
   populated Scorecard (real `structural_shape`/`field_presence` scores) + an **informational**
   verdict with a diagnostic explaining *why* — narrated as informational, never "passing".
2. **Host setup** — in a real repo, `/evalglass setup`. *Expect:* candidate-call-site discovery is
   the first visible output (no "all calls" claim); data-policy prompts are resolved before any
   write; the runtime is vendored and a `proposed` dataset + metrics + CI are scaffolded.
3. **Connect** — `/evalglass connect` against exported OTel/OpenInference JSON (or local trace
   JSONL). *Expect:* import without SDK/network; scaffolded data is `proposed`; no live-pull claim.
4. **Run → view → explain** — `/evalglass run` (vendored), then `/evalglass view` (per-metric;
   `--by-call` groups by explicit subject identity) and `/evalglass explain` (reasons from typed
   fields only).
5. **Compare / baseline** — `/evalglass compare` shows a delta only when `comparable`; `/evalglass
   baseline` promotion is deliberate.
6. **Migration coexistence** — in a repo with an existing `evals/_evalglass/`, `/evalglass setup`
   recognizes it and does not silently overwrite host-owned files.

## Exit criterion (EGP-P1)

A user installs the plugin, runs the bundled quickstart, then evaluates a host repo through
setup → connect → run → view → explain — while every verdict and CI meaning comes from typed
Scorecard / VerdictPayload data, and removing the plugin changes no verdict.
