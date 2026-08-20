# ADR 0055 — Judge execution policy: cache, budgets, and bounded retry

**Status:** Accepted

## Context

A real judge call is a slow, paid, non-deterministic effect. Without controls a host cannot predict
cost, cannot reproduce a run without re-paying, and risks an uncontrolled burst of provider requests.
Every host was reimplementing the same cache, budget, and retry logic behind its command judge.

## Decision

Add a typed, host-owned `JudgeExecutionPolicy` (`judge.execution:`) that wraps the per-effect judge
dispatch. Its default is a no-op (no cache, no budget, no retry), so a run without the block is
byte-identical to the pre-C3 path.

1. **Deterministic cache.** Keyed by the complete score-determining instrument — the judge's
   non-secret identity (adapter/endpoint/model/decoding), the rubric provenance (refs + content
   digest), and the request content (metric/input/output/reference). Modes: `off`, `read_write`,
   `read_only`, `refresh`. A hit avoids the provider and is recorded as the evidence's cache state; a
   corrupt entry fails closed to a miss, never a stale silent score. Any score-determining change
   invalidates the key, so a model or rubric change forces a recompute. Credentials and raw payloads
   are never part of the key.

2. **Budgets checked before dispatch.** `max_requests`, `max_total_tokens`, `max_cost`, and
   `max_wall_seconds` are checked *before* each call; once exhausted, every remaining planned effect
   gets typed non-scored evidence (`MISSING` with a `judge_budget_exhausted` diagnostic), never a
   fabricated value. Successful evidence already collected is never erased.

3. **Bounded retry.** A retryable status set (timeout / provider error) is retried up to a declared
   count with a backoff whose sleep is injected, so the required tier stays fast and deterministic.
   Attempts are recorded on the evidence; retries never turn a failure into a score.

4. **Cost is captured, not embedded.** Cost comes from provider usage when present, else estimated
   from a host-supplied cost table (labelled an estimate). The framework embeds no time-sensitive
   prices; with no cost table, cost is reported unavailable.

5. **Preflight preview.** `preflight` / `run --dry-run` report the cache mode, cache-candidate count,
   the configured budgets, and a conservative upper bound on output tokens (and cost when a cost
   table is supplied) — with no provider call and no cache read.

6. **Concurrency.** The policy carries a validated `concurrency` bound; execution is currently
   sequential (which never exceeds any bound ≥ 1 and keeps output ordering deterministic by plan
   effect id — the safety property the acceptance criteria require). Parallel dispatch under the same
   bound is a deliberate future optimization that preserves these semantics.

## Consequences

- Real judge work is reproducible (cache), bounded (budgets), and resilient (retry), all inspectable
  before a run through preflight, with usage recorded on the persisted evidence (ADR 0054).
- The cache is reproducibility evidence, not calibration evidence — a hit does not make a judge
  authoritative; calibration and an approved threshold still govern gating.
- A run without an execution policy is unchanged; the controls are opt-in and typed.
