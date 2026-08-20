# ADR 0054 — Persist complete judge evidence in the RunRecord

**Status:** Accepted

## Context

A judge `Score` recorded its value and a few provenance refs, but the rich evidence that produced it
— parsed rationale, per-criterion facets, violations, cited evidence, provider/model identity, token
usage, latency, and diagnostics — lived only in the in-memory `EvidenceBundle` and was discarded when
the run was archived. A report or dashboard therefore had to read a host-private cache to explain a
score, and `Score.evidence_refs` pointed at nothing durable. The structured judge output introduced
in ADR 0053 made this gap sharper: the facets/violations/citations existed but were not persisted.

## Decision

Persist the complete judge evidence as a first-class, integrity-covered part of the RunRecord, and
make `Score.evidence_refs` resolve to it.

1. **`RunRecord.evidence`.** An additive, optional list of the run's `JudgeEvidence` records — the
   parsed score/rationale/facets/violations/citations plus instrument refs, usage, and diagnostics
   that produced each judge outcome. It is emitted only when non-empty, so a no-judge run is
   byte-identical, and it is deliberately **off** the Scorecard, which stays compact (summaries and
   refs, never the full records).

2. **Resolvable refs.** Each record has a stable `evidence_id` (`judge:<example>:<metric>`) that a
   judge `Score.evidence_refs` resolves to via `RunRecord.resolve_evidence(...)` — the supported
   projection a report uses instead of untyped dict traversal. A judge score references its record on
   *every* path, so a report can explain a block or a parser failure, not only a successful score.

3. **Integrity.** When evidence is persisted, loading verifies that every `judge:` ref resolves and
   that a numeric judge value's evidence has status `ok` — a dangling ref (a record removed by
   tampering) or a value riding non-`ok` evidence fails closed, on top of the existing RunRecord
   manifest digest. A legacy record with no `evidence` key still loads: its refs are simply
   unavailable on read, never fabricated.

4. **Raw-response retention.** The conservative default drops the raw provider text from the persisted
   evidence — the parsed content and the response fingerprint (portable, verifiable) always remain.
   A host opts in with `judge.retain_raw_response: true`; the choice is part of the run's evidence and
   the fingerprint already covers the raw text, so a redaction change is visible.

5. **Non-judge evidence stays extensible.** Only judge evidence is shaped here; the evidence list is a
   typed collection that a later kind can extend without forcing everything into judge-shaped fields.

## Consequences

- An archived run explains each judge score — rationale, facets, violations, citations, usage — with
  the provider and any host cache removed. This is what Epic D (metric-scoped authority) and Epic E
  (the diagnostic dashboard) build on.
- Tampering that removes or rewrites evidence fails to load, so a green archive cannot quietly lose or
  fake the evidence behind a score.
- The Scorecard stays compact; the heavy evidence lives in the RunRecord and resolves on demand.
