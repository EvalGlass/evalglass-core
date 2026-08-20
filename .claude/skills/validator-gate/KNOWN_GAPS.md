# Validator Gate — known gaps

Explicit, named deferrals. None of these are silent passes: each is a bounded
limitation of the MVP, recorded so a reviewer can see what is *not* yet proven.

- **Content conventions are MVP shapes, not product contracts.** Families read
  artifact `content` via tolerant probes (e.g. `verdict`, `claimed_status`,
  `acts_as`, `decides_verdict`, `baseline.state`, `lane`, `influences_verdict`).
  These are the agreed Execution-Loop/Validator convention while the EvalGlass
  product core (`src/evalglass/`) is a skeleton. When real `RunRecord`/
  `Scorecard` shapes land, revisit the probe field names — the invariants stay,
  the field names may move.
- **No live Execution Loop.** The adapter is built against the documented
  `gate_plan`/`evidence_pack` contract and proven by fixtures; it is not yet
  wired to a running Execution Loop (none is vendored in this repo).
- **Router inference vocabulary is fixed.** `RISK_SURFACE_FAMILIES` maps a
  curated set of risk-surface tokens to families. Unknown tokens are ignored
  during inference (a claim with only unknown surfaces and no `expected_families`
  routes to nothing → BLOCKED). Extending the vocabulary is additive.
- **Timestamp comparison is type-bounded.** `evidence_provenance` compares
  baseline/run timestamps only when they share a Python type (both ints or both
  strings) and treats ISO-8601 strings as lexically ordered. Mixed-type or
  non-lexical timestamps are not compared.
- **Adjacent-gate ingestion is shallow.** The adapter materializes
  `scan_gate_result`/`code_review_result` as typed evidence and enforces the
  authority boundary, but it does not parse Scan Gate / Code Review *findings*;
  it consumes their result as evidence and never reimplements their rules.

Adding coverage for any of these is additive and must not weaken the existing
fail-closed behavior or the seeded bad-case suite.
