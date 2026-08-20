"""Synthetic-generation lane boundary + governed coverage (EG-AT4-7; EG-H3-1; plan §5.5, delta D5).

The synthetic generator ships in EG-H3 as a real harness service — but a **non-lane** one whose
generated data is always ``proposed``. AT2-1 (``test_governance_synthetic.py``) proves the funnel
forces ``proposed`` and fences the declared-status bypass. This slice covers the two parts AT2 did
not:

* the **reference-metric** gate path specifically refuses a synthetic-origin (proposed) dataset —
  a numeric reference score is never permission to gate on generated data;
* the capability is built as a **non-lane** governed surface — its ``eg_m5c.yaml`` row is
  ``covered`` with real ``m5c.synthetic.*`` scenarios, yet no synthetic *generator lane* is
  registered (it feeds the governance funnel, it is not a ``LanePort`` adapter).

Pure, hermetic tests over the live governance/authority surfaces + the coverage registry. New file
so the frozen ``test_governance.py`` canary stays byte-stable (AT1 FS-META).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from evalglass.core import DatasetStatus
from evalglass.core.authority import (
    AuthorityInputs,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.harness.governance import import_synthetic_dataset
from evalglass.harness.lanes import built_in_lanes

_COVERAGE = Path(__file__).resolve().parents[1] / "egts" / "coverage" / "eg_m5c.yaml"
_SYNTHETIC_ROW = "EG-M5C-5"


def _reference_metric_inputs(dataset_status: DatasetStatus) -> AuthorityInputs:
    """A reference metric with every gating precondition met *except* the dataset status."""
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=dataset_status,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        judge_calibration=None,
    )


def test_synthetic_output_is_forced_proposed() -> None:
    """Premise: the only synthetic import funnel forces ``proposed`` (cf. AT2-1)."""
    assert import_synthetic_dataset("g", 5, declared_status="validated").status is (
        DatasetStatus.PROPOSED
    )


def test_synthetic_dataset_cannot_gate_a_reference_metric() -> None:
    """A reference metric over a synthetic (proposed) dataset cannot gate — typed reason."""
    synthetic_status = import_synthetic_dataset("g", 5).status
    resolved = resolve_authority(_reference_metric_inputs(synthetic_status))
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


def test_host_validated_reference_dataset_can_gate() -> None:
    """Specificity: the same reference metric over a host-*validated* dataset is eligible.

    Proves it is the synthetic-forced ``proposed`` status — not the rest of the config — that
    blocks the reference gate.
    """
    resolved = resolve_authority(_reference_metric_inputs(DatasetStatus.VALIDATED))
    assert resolved.can_gate is True
    assert resolved.reasons == []


def test_no_synthetic_generator_lane_is_registered() -> None:
    """The generator is absent: no ``built_in_lanes()`` entry mentions synthetic generation."""
    names = built_in_lanes().names()
    assert not any("synthetic" in name for name in names), names


def test_synthetic_capability_is_covered_as_a_non_lane() -> None:
    """The synthetic row is ``covered`` with real ``m5c.synthetic.*`` scenarios — the generator is
    built — but it remains a non-lane (no synthetic lane is registered, asserted above)."""
    rows = yaml.safe_load(_COVERAGE.read_text(encoding="utf-8"))["rows"]
    row = next(r for r in rows if r["product_ticket"] == _SYNTHETIC_ROW)
    assert row["status"] == "covered"
    assert row.get("scenario_ids"), "a covered row needs real scenario ids"
    assert all(sid.startswith("m5c.synthetic.") for sid in row["scenario_ids"])


@pytest.mark.parametrize("declared", ["validated", "approved", "gating", "VALIDATED"])
def test_synthetic_funnel_strips_every_optimistic_status(declared: str) -> None:
    """Sensitivity over the funnel: no claimed status survives import."""
    assert import_synthetic_dataset("g", 1, declared_status=declared).status is (
        DatasetStatus.PROPOSED
    )
