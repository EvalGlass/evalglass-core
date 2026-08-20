# ADR 0046 — `connect --live` verb over the shipped connector lanes

- **Status:** accepted
- **Date:** 2026-07-23
- **Related:** the connector boundary + the three live connectors
  ([0033](0033-live-trace-connector-boundary.md), [0034](0034-langfuse-trace-connector.md),
  [0035](0035-phoenix-trace-connector.md), [0036](0036-langsmith-trace-connector.md)); the lane-attach
  seam ([0031](0031-runner-attach-seam-and-lane-results.md)); the config-reachable unit ladder
  ([0045](0045-config-reachable-unit-ladder.md)).

## Context

Getting an agent's real behavior *into* EvalGlass is the biggest adoption friction. The three live
connectors (Langfuse / Phoenix / LangSmith) already ship as opt-in, deletable `TRACE_SOURCE` lanes,
and the runner already executes them via `_attach_pre_core_lanes`. But the only way to use one was
to **hand-author a `lanes:` block** in `evalglass.yaml` with the right dotted module, credential
env-refs, endpoint, and data-policy — expert-only, and the site's single most-repeated "planned"
claim (`connect --live` "isn't wired").

This is an **ergonomics + honesty** gap, not missing measurement: the capability exists; it is
unreachable by a verb, and the site under-claims it.

## Decision

Add a first-class **`connect --live <platform>`** verb that scaffolds/enables the correct connector
lane. **Scaffold-then-run**, not pull-immediately.

1. **The verb writes config; the connector does the transport.** `connect --live langfuse` (or
   `phoenix`/`langsmith`) writes/updates a `lanes:` entry enabling the matching connector lane. The
   subsequent `evalglass run` executes it through the existing seam (`_attach_pre_core_lanes` →
   `LaneRegistry.resolve` → the lazily-imported connector). Rationale: the verb stays hermetic
   (writes config, makes no live call), reuses the proven seam, preserves host-owned config, and is
   idempotent.

2. **The config the verb writes.** An enabled `LaneConfig`: `{name: <platform>-trace, enabled: true,
   data_policy: <policy>, options: {endpoint, credentials, project?, limit?}}`. Credentials are
   **environment-variable names** (references), never literal secrets — a literal is rejected by the
   connector boundary's `parse_provider_options` (reused), and the error never echoes the value.
   `data_policy` **defaults to `unknown`** (fail-closed egress: the connector refuses the pull before
   any client call until the host consciously sets `permitted`/`redacted`). `enabled: true` so a
   following `run` executes it. `apply_connect` upserts the lane by name (idempotent — re-running
   updates in place, never duplicates) and preserves every other config key. (YAML comments are not
   preserved: PyYAML has no comment-round-trip API, so the verb rewrites the data.)

3. **No provider SDK, no `adapters/trace_*` module on any required path.** `connect.py` imports only
   the connector *boundary* (`_connector_boundary`, SDK-free) and `LaneConfig` — never a lane module.
   The lane-boundary import guard (`tests/core_isolation/test_lane_boundary.py`) covers the new module;
   deleting a connector leaves the verb and the hermetic required tier byte-identical, and a missing
   extra / endpoint / credential is a clean `SKIPPED` (`MissingPrerequisite`), never a crash.

4. **Authority.** A live pull is a trace source carrying no validated gold, so a live-connected run
   dilutes to `PROPOSED` and resolves `informational` — it **cannot gate**. An approved gating
   threshold over pulled data never activates a gate (it stays informational, never a laundered pass).

5. **Maturity: leave the lanes `PLANNED`; the site owns the badge.** The three lanes stay
   `Maturity.PLANNED` metadata rather than being rebadged to `EXPERIMENTAL` here. Rationale: the
   maturity field is never read by the verdict path, the ontology/status registry already encodes
   `langfuse`/`phoenix`/`langsmith` as `planned` capabilities, and rebadging would ripple through the
   status/ontology suites without changing behavior. The verb makes the capability *reachable*
   regardless of the tag; the skill prose describes it honestly as **opt-in / experimental** (a
   future marker the honesty scanner accepts). The public site owns the user-facing badge.

## Consequences

- `connect --live <platform>` scaffolds a valid, enabled lane; a following `run` pulls + normalizes
  traces through the existing seam and emits an honest `informational` scorecard on `proposed` data.
- **No false confidence:** the verb is framed as "real but opt-in, off the required path," never
  "production live tracing"; a live-connected run never reads as a proven pass; the fail-closed
  `unknown` default means egress is refused until the host consciously permits it.
- **Deletion-invariant + SDK-free required tier** are preserved and tested.
- **Proof split:** the required-tier hermetic proof (`tests/egts/suites/test_p2_connect_live_proof.py`)
  drives the real `run_config` over an **injected fake fetch** (a recorded payload), asserting the
  lane runs, dilutes authority, and stays informational, plus clean-skip / no-gate / secret-rejection
  negative controls. A real-network pull is the manual, secret-gated `live-lanes` tier (recorded
  export as the documented hermetic substitute); the CI contract for that tier is guarded by
  `tests/test_live_connector_workflow.py`.
- The site's connector "planned/coming" copy is now an under-claim (the framework ships the verb);
  the site edit is a separate site-repo PR.
