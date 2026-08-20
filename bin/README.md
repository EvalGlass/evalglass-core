# `bin/` — plugin launchers (integration-time only)

- **`evalglass-launch`** — the integration-time launcher. It runs the **bundled** EvalGlass skill
  from `${CLAUDE_PLUGIN_ROOT}/src` (`python -m evalglass.installer <discover|plan|install|revendor>`),
  so a marketplace-only user needs no `pip install`. It resolves the plugin root from
  `${CLAUDE_PLUGIN_ROOT}` (or its own location), forwards arguments verbatim, and reports a missing
  bundled framework as a **setup error (exit 2)**, never an evaluation result.

It is **integration-time only** and is **never vendored** into a host (ADR 0022). Host *evaluation*
runs never use it — they use the host's vendored `_evalglass`
(`PYTHONPATH=evals python -m _evalglass.harness.cli …`). Nothing the plugin writes into a host
(config, scaffolds, CI) may reference this launcher or `${CLAUDE_PLUGIN_ROOT}`.
