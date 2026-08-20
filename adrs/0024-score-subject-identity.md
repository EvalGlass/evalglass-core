# ADR 0024 — Score subject identity (additive provenance)

- **Status:** accepted
- **Date:** 2026-06-02
- **Reuses:** ADR 0022 (plugin packaging — F1 is the sanctioned framework follow-up), the M0 core contracts
- **Source:** `docs/PLUGIN_TRANSFORMATION_PLAN.md` §4.4 (F1 note), §10 F1; `docs/plugin_transformation_jira_tickets.xlsx` (EGP-F1)

## Context

The plugin's `/evalglass view --by-call` (per-LLM-call grouping) was deliberately blocked at v1:
`Score` carries no identity of the subject it measured, and the run fingerprint only hashes the
*set* of example ids — so a reader could only guess a per-call grouping from list order, which is
false confidence. `Example` and `EvalUnit` already carry identity; `Score` does not.

F1 is the **one framework change** in the plugin series (plan §4.4, §10). It is additive provenance
only — it adds the subject's identity to a `Score` so a reader can group honestly. It must not
change score *meaning*, aggregation, or the Verdict Engine, and it must keep every public artifact
JSON-compatible and backward-compatible.

## Decision

1. **Additive optional fields on `Score`: `example_id: str | None` and `unit_id: str | None`.**
   Flat fields (not a nested object) — the shape the plan and EGTS expect. Default `None`. This is
   *subject identity* (which `Example`/`EvalUnit` a score came from), **not** new metric meaning,
   authority, or source-function attribution.

2. **Serialization is backward-compatible and fail-closed.**
   - `to_dict` emits `example_id`/`unit_id` **only when present** (like `diagnostics`/`provenance`),
     so an identity-less score serializes byte-for-byte as before — old snapshots are unchanged.
   - `from_dict` accepts records **without** the fields (→ `None`) and **rejects a non-string**
     value when present (reuses `_opt_str`). Old `runrecord.json` artifacts still parse.
   - `ScoreBatch` carries identity through its member `Score`s — no separate batch field.

3. **No change to meaning.** Aggregation eligibility, the cardinal "non-scored carries no value"
   rule, provenance fingerprints, and the Verdict Engine are untouched. `check_core_isolation`
   stays green (stdlib-only, effect-free). Aggregate/synthetic scores may carry explicit stable
   identities (e.g. an aggregate or route-error subject) but never invent a per-call one.

4. **Population is the harness/engine's job, not every evaluator's.** Per-example evaluator output
   is stamped with the current `example_id`/`unit_id` by the engine collection + harness paths
   (F1-3); built-ins and host evaluators need not know about identity or `view --by-call`.

5. **Gated rollout.** `/evalglass view --by-call` ships **only after** an artifact-shape gate
   (F1-4) proves a real `runrecord.json` carries the identity — never enabled on the contract
   alone. Per-source-*function* mapping (a score → a discovered call site) needs trace↔call-site
   correlation that does not exist and remains an advanced extension (EGP-A1-7), explicitly out of
   scope here.

## Consequences

- The public `Score`/`RunRecord` JSON grows two optional keys; round-trip and old-artifact-compat
  tests pin both the additive emit and fail-closed parse. Snapshots that lacked identity are
  unchanged (emit-only-when-present).
- `view --by-call` becomes possible once F1-3/F1-4 land; the plugin reader groups by explicit
  identity, never by score order (F1-5).
- This is the only frozen-core exception in the plugin series; it follows the M-series loop
  (tests-first → scan-gate + validator-gate → review → PR → CI), not the packaging loop.

## Alternatives considered

- **A nested `subject: {example_id, unit_id}` object.** Rejected: flat fields match the plan/EGTS
  wording, serialize more compactly, and are simpler to make emit-only-when-present.
- **Have evaluators return identity.** Rejected: it would force every built-in and host evaluator
  to plumb identity and could let an evaluator misattribute a score. The engine/harness already
  knows the current `Example`/`EvalUnit` — stamp there.
- **Reconstruct per-call grouping from `Example` order in the reader.** Rejected: that is the exact
  order-guessing false confidence F1 exists to remove.
