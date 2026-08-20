# Marketplace listing & community submission (EGP-P2-7)

The submission package for the EvalGlass plugin. **Submit only after** strict validation, the
honesty audit, manifest consistency, and five-way version alignment are green (see
[`RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md)). Nothing here may overclaim.

## Listing copy

**Name:** EvalGlass — **Tagline:** AI-safety evaluation for agentic apps; honest, local-first scores.

**Description (marketplace):**
> EvalGlass installs a local-first evaluation framework into your repo and **stops for host
> validation before anything can gate**. It discovers candidate LLM call sites, scaffolds
> `proposed` datasets/metrics/CI, and runs a single Verdict Engine that reports only what the
> evidence honestly supports — informational by default, never a manufactured pass.

## Install instructions (verbatim)

```text
/plugin marketplace add EvalGlass/evalglass-core
/plugin install evalglass-core@evalglass
```

The install target is `<plugin>@<marketplace>` (ADR 0062): the plugin `name` is `evalglass-core` and the
marketplace `name` is `evalglass`, so `evalglass-core@evalglass` resolves the `evalglass-core` plugin
inside the `evalglass` marketplace — the `@evalglass` suffix is the marketplace, not the
repo slug.

## Keywords / GitHub topics

`claude-code`, `claude-code-plugin`, `agent-skills`, `ai-safety`, `llm-eval`, `evaluation`, `ci`,
`promptfoo`, `deepeval`, `llm-testing`, `llm-as-judge`.

## Positioning (honest, one line)

Local-first, single Verdict Engine, typed authority, no false confidence — a defensible CI gate
whose green means exactly what the evidence supports. Not a feature race with
promptfoo / DeepEval / Ragas / MLflow.

## Media

Above-the-fold demo from [`examples/demo`](../../examples/demo/) (reproducible cast/GIF). It shows a
populated Scorecard and an informational verdict with a diagnostic. Per-call grouping
(`view --by-call`, by explicit score subject identity) is available; score→source-function mapping
stays an advanced extension.

## Allowed vs. disallowed

- **Allowed:** the description above, install commands, the reproducible demo, scoped badges, GitHub
  topics, stars/used-by once they exist.
- **Disallowed:** fabricated testimonials, endorsement logos, download/star counts that don't exist,
  or any safety/correctness claim — consistent with the project honesty charter and the honesty-audit
  gate.

## Submission steps

1. Confirm `RELEASE_CHECKLIST.md` is fully green and `v0.1.0` is tagged.
2. Open the listing on the community marketplace / directories (e.g. awesome-claude-code) using the
   copy above.
3. Link the repo, the demo, and the CHANGELOG; do not add any signal the project hasn't earned.
