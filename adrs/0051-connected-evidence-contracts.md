# ADR 0051 — Connected-evidence contracts: import manifests, behavior layers, assembly, references

**Status:** Accepted

## Context

Field integrations reached a useful first run only after a host added a disciplined
evidence-assembly layer around the shipped connectors. The recurring gaps were all at the boundary
where recorded behavior *enters* an evaluation:

- **A silent empty/partial import looked complete.** A connector reported "imported N traces" but a
  developer could not tell whether full observations, tool data, parser failures, or only an empty
  valid response came back — so an empty or partial pull could pass for complete behavioral
  evidence.
- **The trace export was not the whole behavior.** A flattened trace conflated the raw model
  output, the application-visible output, and the parser's own diagnostics. A structured-output call
  the application's parser rejected was dropped, so the parser failure — the very thing worth
  measuring — disappeared instead of reading as evidence.
- **Provider observation lists were flattened.** Langfuse's list endpoint returns each trace's
  observations as bare IDs; the connector fell back to a single trace-level span, losing the call
  hierarchy.
- **Cross-record joins were bespoke.** Joining trace calls, parser outcomes, and application state
  into evaluation examples required a hand-written dataset builder per host.
- **Proposed references had no lifecycle.** There was a wide gap between "no reference" and
  "validated gold", and no standard way to draft silver references without risking them being
  treated as gold.

## Decision

Absorb the generic parts of that host work as first-class, typed, host-owned contracts, none of
which grants authority.

1. **First-class local import + fail-closed connect.** `connect --from <export> --format <...>`
   registers an exported trace file as an ordinary `traces:` route with no credentials and no
   provider SDK; the export is validated with the production normalizer before the config is
   touched. Both connect modes require an existing runnable config (or `--init` for a conservative
   informational scaffold), resolve stored paths against the config directory, and write atomically.

2. **Per-source coverage manifests.** Every source read (dataset, local trace, or connector lane —
   including a skipped/blocked one) produces exactly one typed `SourceImportManifest`: reconciled
   counts (seen / emitted / rejected / trace-level-fallback), behavior-layer availability, and a
   typed completeness (`complete_within_declared_scope` / `partial` / `empty` / `blocked`). It is an
   additive `RunRecord.source_manifests` side channel — evidence only, deliberately off the
   Scorecard, so an empty/partial import is visible without touching verdict, CI, or exit. Safe
   identity only; no endpoint URL, vendor object, or secret is retained.

3. **Behavior-layer preservation + bounded hydration.** Trace normalization keeps raw model output,
   application-visible output, and parser diagnostics distinct; a parser-rejected span is a unit
   carrying its raw output and diagnostics (its missing application output reads as non-evaluable,
   never a fabricated zero), and an output-only span is byte-identical to before. The opt-in
   Langfuse connector hydrates bare-ID observation lists into observation-level spans, bounded by a
   fixed ceiling and best-effort, with any shortfall visible as trace-level fallback in the manifest.

4. **Declarative evidence assembly.** An `assemble` verb runs a declarative `evidence_pipeline`:
   named local sources (dataset / trace export / opt-in argv snapshot command), typed joins with
   declared cardinality, and a field projection preserving behavior layers. It emits an ordinary
   Example JSONL (routing through the normal dataset contract — no second scoring engine) plus an
   evidence-assembly manifest with per-field lineage, a config digest, and an output digest. Each
   cardinality violation is a distinct diagnostic that drops the offending row; snapshot commands
   are argv-only, timeout-bounded, root-relative, and egress-gated.

5. **Proposed-reference lifecycle.** A host-owned lifecycle
   `draft -> proposed -> reviewed -> validated -> retired`. A drafted reference always starts
   proposed and refuses to copy the candidate output (leakage). Only an explicit host review record
   whose reviewer is neither an agent identity nor the reference author can reach `validated`;
   EvalGlass verifies the record, never writing `validated` itself. Reference content is
   content-addressed, and a proposed reference maps to a proposed dataset status — reusing the
   existing authority, so it scores informationally and cannot support a validated-dataset gate.

## Consequences

- New public surfaces: the `assemble` verb; `connect --from`/`--format`/`--init`; the optional
  `RunRecord.source_manifests` list; the `evidence-assembly` and `reference-set` artifact schemas.
- Backward compatible: the manifest list is emitted only when non-empty, so a run with no imported
  sources is byte-identical; an output-only span and an existing config are unchanged.
- Authority is reused, never duplicated. None of these contracts grants gating authority; a proposed
  reference and a partial/empty import remain informational, and the single Verdict Engine is
  untouched.
- The managed runtime keeps its no-provider-SDK required-tier boundary: hydration and connector work
  stay lazy, injectable, and hermetically testable; the assembly and reference modules are
  stdlib-and-core-only.
