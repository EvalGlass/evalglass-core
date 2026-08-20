# ADR 0052 — OpenAI-compatible judge as a first-class config adapter

**Status:** Accepted

## Context

A host that wanted a real LLM judge (not the deterministic fake) had two options: write a command
judge subprocess (ADR 0042) that itself calls a provider, or enable the `openai-judge` extension
lane (ADR 0040). The lane was never wired into the config-driven scoring path — a configured
`JUDGE_MODEL` lane was recorded `SKIPPED` before core, so it produced no evidence. In practice every
host therefore reimplemented the same provider concerns (endpoint, credential, timeout, size limits,
JSON parsing) behind a command wrapper.

Meanwhile `JudgeConfig` accepted only `fake` and `command`, and `_build_judge_model` constructed only
those two. The `OpenAICompatibleJudgeModel` adapter already existed (generic stdlib-`urllib`
transport, HTTPS-only, host-injected rubrics) but was unreachable from a normal `run`.

## Decision

Promote the OpenAI-compatible judge into the config-driven measurement path, and retire the
now-redundant `openai-judge` lane.

1. **`judge.adapter: openai_compatible`.** `JudgeConfig` gains a third adapter alongside `fake` and
   `command`, with `endpoint`, `model`, `credential_env`, bounded decoding/size (`max_input_chars`,
   `max_output_tokens`, `response_format`), an explicit `allow_insecure_loopback` policy, and a
   non-secret `headers` allowlist. Every field parses or fails closed; unknown keys are rejected.

2. **The credential is an environment-variable *name*, resolved only at effect time.** `credential_env`
   holds a name (validated against an env-var-name pattern so a pasted secret is refused at the config
   boundary). The secret is read from the environment in `_build_judge_model` — never stored in
   config, plan, provenance, diagnostics, or any artifact. A declared-but-unset credential is an
   unavailable state (typed `MISSING` evidence, no provider call), never a fabricated score.

3. **HTTPS-only except an explicit loopback policy.** A plaintext endpoint is refused unless
   `allow_insecure_loopback` is set *and* the host is a loopback address — for a local judge server
   under test, never public plaintext egress.

4. **The adapter is imported lazily and stays deletable.** `_build_judge_model` imports
   `adapters/judge_openai.py` inside the function, only when `openai_compatible` is configured, so a
   fake/no-judge run imports no provider transport and deleting the adapter leaves the required (fake)
   suite green. The required tier stays hermetic (stdlib `urllib` only, no provider SDK); injected
   transport covers the request/response contract.

5. **Capability and authority are unchanged.** The adapter reports `JudgeCapability.MEASUREMENT`, but
   an uncalibrated real judge still resolves informational — only host-owned calibration plus an
   approved threshold makes the gate live, through the single Verdict Engine. The judge identity
   (adapter, endpoint, model, decoding) enters the gating provenance so a model/endpoint swap breaks
   comparability; the credential never does.

6. **Retire the `openai-judge` lane.** With the adapter reachable from config, the lane was a
   duplicate — and a misleading one, since it only ever recorded `SKIPPED`. It is removed from
   `built_in_lanes()`; the host command judge (ADR 0042) and the `live-judge` lane (ADR 0016, a
   different host-endpoint contract) remain as escape hatches. This is a public-surface change to the
   lane roster; a config naming the retired lane now fails closed with an unknown-lane error.

## Consequences

- A host configures a real OpenAI-compatible judge with configuration alone — no provider subprocess.
- The required suite stays hermetic and provider-SDK-free; the adapter's deletion and import-boundary
  guarantees migrate from the lane to the config path and are proven there.
- Provenance/comparability now turn on the judge's endpoint/model/decoding identity, not just an
  adapter name.
- The `openai-judge` lane name is no longer valid config; hosts select the judge through
  `judge.adapter: openai_compatible` instead.
