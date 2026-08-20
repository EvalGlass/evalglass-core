"""Execution Loop adapter (VG-P2-1, VG-P2-2).

Convenience plumbing the Execution Loop calls: load the evidence pack,
materialize adjacent-gate evidence (Scan Gate / Code Review results), invoke the
runner, optionally write one validator.result.json, and return it with its path.
The adapter changes no gate selection and synthesizes no final status — policy
stays in the core, and the Execution Loop owns the decision_record.

Adjacent-gate handling (VG-P2-2): pack-level ``scan_gate_result`` and
``code_review_result`` are materialized as typed artifacts (scan_gate / external
authority) so families can cite them as evidence. Because they are not product
authority, they can prove mechanical prerequisites but can never become the
verdict authority — and a claim that requires one BLOCKS precisely when it is
absent (the index reports the missing required artifact). Validator never
reimplements Scan Gate rules or the Code Review rubric.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.composer import write_outputs
from scripts.contracts import (
    ArtifactKind,
    ArtifactRef,
    Authority,
    EvidencePack,
    Status,
    ValidatorResult,
)
from scripts.evidence import EvidenceError, load_pack
from scripts.runner import run_validation

if TYPE_CHECKING:
    from typing import TextIO

# Well-known ids a claim uses to require adjacent-gate evidence.
SCAN_GATE_RESULT_ID = "scan_gate_result"
CODE_REVIEW_RESULT_ID = "code_review_result"


def materialize_adjacent(pack: EvidencePack) -> EvidencePack:
    """Surface pack-level scan/review results as typed evidence artifacts."""
    extra: list[ArtifactRef] = []
    boundary = {k: list(v) for k, v in pack.source_boundary.items()}
    if pack.scan_gate_result is not None:
        extra.append(
            ArtifactRef(
                id=SCAN_GATE_RESULT_ID,
                kind=ArtifactKind.SCAN_RESULT,
                authority=Authority.SCAN_GATE,
                content=pack.scan_gate_result,
                produced_by="scan-gate",
            )
        )
        boundary.setdefault("scan_gate", []).append(SCAN_GATE_RESULT_ID)
    if pack.code_review_result is not None:
        extra.append(
            ArtifactRef(
                id=CODE_REVIEW_RESULT_ID,
                kind=ArtifactKind.REVIEW_RESULT,
                authority=Authority.EXTERNAL,
                content=pack.code_review_result,
                produced_by="code-review",
            )
        )
        boundary.setdefault("external_contracts", []).append(CODE_REVIEW_RESULT_ID)
    if not extra:
        return pack
    # Don't duplicate ids the pack already declares explicitly.
    existing = {a.id for a in pack.artifacts}
    extra = [a for a in extra if a.id not in existing]
    if not extra:
        return pack
    return replace(pack, artifacts=pack.artifacts + extra, source_boundary=boundary)


def run_adapter(
    source: dict[str, Any] | str | Path,
    *,
    out_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
    checkpoint: str | None = None,
    trace_sink: TextIO | None = None,
) -> tuple[ValidatorResult, str | None]:
    """Validate via the Execution Loop entrypoint; return (result, written path).

    When `trace_sink` is given, a non-authoritative debug trace is written to it
    (it never changes the result).
    """
    try:
        pack = load_pack(source)
    except EvidenceError as exc:
        result = ValidatorResult(
            status=Status.BLOCKED,
            checkpoint=checkpoint or "unknown",
            blocked_on=[f"evidence: {exc}"],
        )
    else:
        result = run_validation(
            materialize_adjacent(pack), checkpoint=checkpoint, trace_sink=trace_sink
        )

    written: str | None = None
    if out_path is not None:
        write_outputs(result, out_path, markdown_path)
        written = str(out_path)
    return result, written
