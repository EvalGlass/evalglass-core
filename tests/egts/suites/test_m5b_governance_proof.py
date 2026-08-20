"""EGTS-M5-6 — generated-evidence governance proof (Trust Proof).

Proves the real governance surfaces refuse to let generated artifacts manufacture authority:
synthetic data stays `proposed`; an annotation is an authority input only with a validation record;
a benchmark gives threshold evidence but can never approve a threshold. Run via
``egts test-lane evidence-workflows``. Negative controls per invariant (``tests/CLAUDE.md §12``).
"""

from __future__ import annotations

import pytest

from evalglass.core import DatasetStatus, Direction
from evalglass.harness.calibration import ApprovedThreshold
from evalglass.harness.governance import (
    AnnotationImport,
    BenchmarkEvidence,
    GovernanceError,
    approve_threshold_from_benchmark,
    import_synthetic_dataset,
)


def test_m5b_synthetic_data_stays_proposed() -> None:
    """m5b.governance.synthetic_is_proposed — generated data never self-validates."""
    ds = import_synthetic_dataset("gen", 100)
    assert ds.status is DatasetStatus.PROPOSED


def test_negctl_synthetic_cannot_self_declare_validated() -> None:
    # Even a hopeful "validated" claim is made safe (proposed), never honored.
    ds = import_synthetic_dataset("gen", 100, declared_status="validated")
    assert ds.status is DatasetStatus.PROPOSED


def test_m5b_annotation_needs_validation_record_to_be_authority() -> None:
    """m5b.governance.annotation_needs_validation — no record → informational, not authority."""
    informational = AnnotationImport(annotation_id="a1", value=1.0)
    assert informational.is_authority_input is False
    validated = AnnotationImport(annotation_id="a1", value=1.0, validation_record="val-2026-05-31")
    assert validated.is_authority_input is True


def test_negctl_blank_validation_record_is_not_authority() -> None:
    assert (
        AnnotationImport(annotation_id="a1", value=1.0, validation_record="   ").is_authority_input
        is False
    )


def test_m5b_benchmark_supports_but_cannot_approve() -> None:
    """m5b.governance.benchmark_evidence_not_approval — benchmark supports, never approves."""
    threshold = ApprovedThreshold(
        value=0.8,
        direction=Direction.HIGHER_IS_BETTER,
        variance=0.02,
        approver="domain-expert",
        rationale="validated over 20 runs",
        version="1",
    )
    evidence = BenchmarkEvidence(metric="m", observed=0.9, runs=20)
    assert evidence.supports(threshold) is True  # informational support of an approved threshold


def test_negctl_benchmark_cannot_approve_a_threshold() -> None:
    with pytest.raises(GovernanceError):
        approve_threshold_from_benchmark(BenchmarkEvidence(metric="m", observed=0.9, runs=20))
