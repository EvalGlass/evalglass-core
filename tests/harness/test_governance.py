"""Layer-1 unit tests for generated-evidence governance (EG-M5-6 S2)."""

from __future__ import annotations

from evalglass.core import Direction
from evalglass.harness.calibration import ApprovedThreshold
from evalglass.harness.governance import AnnotationImport, BenchmarkEvidence, SyntheticDataset


def test_annotation_to_dict_omits_absent_record() -> None:
    assert AnnotationImport(annotation_id="a", value=1).to_dict() == {
        "annotation_id": "a",
        "value": 1,
    }


def test_annotation_to_dict_includes_record() -> None:
    out = AnnotationImport(annotation_id="a", value=1, validation_record="v1").to_dict()
    assert out["validation_record"] == "v1"


def test_synthetic_dataset_status_is_proposed() -> None:
    assert SyntheticDataset(name="g", example_count=3).status.value == "proposed"


def test_benchmark_supports_lower_is_better() -> None:
    threshold = ApprovedThreshold(
        value=0.2,
        direction=Direction.LOWER_IS_BETTER,
        variance=0.01,
        approver="x",
        rationale="r",
        version="1",
    )
    assert BenchmarkEvidence(metric="latency", observed=0.1, runs=5).supports(threshold) is True
    assert BenchmarkEvidence(metric="latency", observed=0.5, runs=5).supports(threshold) is False
