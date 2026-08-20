# ADR 0021 — Generated-evidence governance (annotation / synthetic / benchmark)

- **Status:** accepted
- **Date:** 2026-05-31
- **Reuses:** ADR 0012 (`AuthorityRecord`), ADR 0015 (`ApprovedThreshold`)

## Context

M5 enables useful workflows that produce *generated or unvalidated* evidence —
annotation outputs, synthetic datasets, benchmark results (build contract §2/§10/§12;
EG-M5-6). The hazard is that such evidence quietly becomes authority: synthetic data
treated as validated gold, an unreviewed annotation gating a run, or a benchmark
"approving" a threshold without a human approver. The no-false-confidence rule
(CLAUDE.md §1/§19) requires these to stay non-authoritative until host validation.

## Decision

`harness/governance.py` encodes three fail-closed invariants; it fabricates no authority
and reuses the existing host-owned approval records (`AuthorityRecord`, `ApprovedThreshold`).

| Artifact | Rule | Mechanism |
|---|---|---|
| Synthetic dataset | status is **always `proposed`** until a host validates it | `import_synthetic_dataset(...)` ignores any `declared_status`; `SyntheticDataset.status` is fixed to `PROPOSED`. |
| Annotation output | an **authority input only with a host validation record** | `AnnotationImport.is_authority_input` is true only for a non-blank `validation_record`; else informational. |
| Benchmark result | **threshold *evidence*, never approval** | `BenchmarkEvidence.supports(threshold)` informs against an already-approved threshold; `approve_threshold_from_benchmark(...)` **raises `GovernanceError`** — only a host `ApprovedThreshold` (with an approver) can approve. |

Governance docs (`docs/EXTENSION_GOVERNANCE.md`) carry the extension-authoring guide,
the rejected-shortcuts list, and the review checklist (when a new port / dependency /
authority record needs review).

## Consequences

- Generated/annotated/benchmark evidence can inform the host but can never gate on its
  own; authority still requires a host validation record / approved threshold.
- A benchmark cannot manufacture an approver; the calibration path (ADR 0015) stays the
  only route to a gating threshold.
- Reports separate generated/proposed from validated/gating because the status/authority
  is unchanged — these artifacts simply never resolve to `gating` without host validation.

## Alternatives considered

- **Let `import_synthetic_dataset` honor a `validated` claim.** Rejected — that is exactly
  the auto-validation hole; the claim is accepted but never honored (forced `proposed`).
- **Let a benchmark approve a threshold above some confidence.** Rejected — approval is a
  human act with an approver and rationale (ADR 0015); a benchmark only supplies evidence.
- **Raise on an annotation without a validation record.** Rejected — an unreviewed
  annotation is still useful *informational* evidence; it is simply not an authority input.
