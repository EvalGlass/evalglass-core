"""EGTS-M5C-5 — synthetic-data generation proof (Route Proof, Trust Proof).

Proves the real product synthetic generator (EG-H3) over real generated output:

* ``m5c.synthetic.forced_proposed`` — a generated dataset is written locally with reviewable
  metadata and its status is always ``proposed``;
* ``m5c.synthetic.bypass_cannot_gate`` — synthetic-origin (proposed) data resolves
  ``can_gate=false`` with a ``dataset_proposed`` reason, and a declared validated/approved/gating
  status is stripped by the import funnel — there is no bypass to validated;
* ``m5c.synthetic.host_validated_specificity`` — a host-validated (non-synthetic) dataset under the
  same preconditions remains eligible to gate, so the guard is not a blanket deny.

Scenario ids map to EG-M5C-5; the full validator-gate acceptance pack is rebuilt in EG-H5-4.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.harness.governance import import_synthetic_dataset
from evalglass.harness.synthetic import generate_synthetic_dataset

_SEEDS = [{"input": "2+2", "output": "4", "reference": "4"}]


def _gating_inputs(dataset_status: DatasetStatus) -> AuthorityInputs:
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=dataset_status,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        judge_calibration=JudgeCalibration.CALIBRATED,
    )


def test_m5c_synthetic_forced_proposed(tmp_path: Path) -> None:
    """m5c.synthetic.forced_proposed — real generated output is local, reviewable, and proposed."""
    generated = generate_synthetic_dataset("gen", root=tmp_path, seed_examples=_SEEDS, count=3)
    assert generated.status is DatasetStatus.PROPOSED
    assert generated.dataset_path.is_file()
    metadata = json.loads(generated.metadata_path.read_text(encoding="utf-8"))
    assert metadata["origin"] == "synthetic"
    assert metadata["status"] == "proposed"


def test_m5c_synthetic_bypass_cannot_gate(tmp_path: Path) -> None:
    """m5c.synthetic.bypass_cannot_gate — synthetic-origin data cannot gate, and no declared status
    can flip it to validated."""
    generated = generate_synthetic_dataset("gen", root=tmp_path, seed_examples=_SEEDS, count=3)
    resolved = resolve_authority(_gating_inputs(generated.status))
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons
    for declared in ("validated", "approved", "gating"):
        assert import_synthetic_dataset("x", 3, declared_status=declared).status is (
            DatasetStatus.PROPOSED
        )


def test_m5c_synthetic_host_validated_specificity() -> None:
    """m5c.synthetic.host_validated_specificity — a host-validated (non-synthetic) dataset under the
    same preconditions resolves can_gate=true; the guard is specific, not a blanket deny."""
    resolved = resolve_authority(_gating_inputs(DatasetStatus.VALIDATED))
    assert resolved.can_gate is True
    assert resolved.reasons == []


def test_negctl_synthetic_status_is_a_fixed_property_not_a_settable_field(tmp_path: Path) -> None:
    """Negative control: status is a fixed property (always proposed), not a constructor field —
    there is no path that builds a generated dataset claiming validated."""
    import dataclasses

    generated = generate_synthetic_dataset("gen", root=tmp_path, seed_examples=_SEEDS, count=1)
    assert generated.status is DatasetStatus.PROPOSED
    field_names = {f.name for f in dataclasses.fields(generated)}
    assert "status" not in field_names, "status must be a derived property, never a settable field"


@pytest.mark.parametrize("count", [1, 5, 10])
def test_synthetic_generation_is_reproducible(tmp_path: Path, count: int) -> None:
    a = generate_synthetic_dataset("gen", root=tmp_path / "a", seed_examples=_SEEDS, count=count)
    b = generate_synthetic_dataset("gen", root=tmp_path / "b", seed_examples=_SEEDS, count=count)
    assert a.dataset_path.read_bytes() == b.dataset_path.read_bytes()
