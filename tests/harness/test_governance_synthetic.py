"""Governance 1A — synthetic data is always ``proposed`` and cannot gate (EG-AT2-1).

Source: alignment test plan §6 Part 1A and §5.5 (with the GAP-7 fix).

The funnel ``import_synthetic_dataset`` always forces ``proposed``, so asserting
*that* alone proves nothing about a future generator. These tests therefore also
fence the **bypass** path: a synthetic-origin dataset has no way to claim
``validated`` even when constructed directly, and feeding its status into the real
``resolve_authority`` path resolves ``can_gate=False``. The specificity control
proves a host-*validated*, non-synthetic dataset with the same other preconditions
*does* become eligible — so the synthetic dilution, not the rest of the config, is
what blocks the gate.

These are pure, hermetic unit tests over the live governance + authority surfaces.
They live in a new file so the frozen canary ``test_governance.py`` stays byte-stable
(AT1 FS-META).
"""

from __future__ import annotations

import dataclasses

import pytest

from evalglass.core import DatasetStatus
from evalglass.core.authority import (
    AuthorityInputs,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.harness.governance import SyntheticDataset, import_synthetic_dataset
from tests.fixtures.synthetic import (
    make_synthetic_request,
    make_synthetic_request_claiming_validated,
)

# Every declared status a hopeful generator might claim — all must be stripped.
_DECLARED_STATUSES = [
    "validated",
    "approved",
    "gating",
    "retired",
    "proposed",
    "",
    "VALIDATED",
    "anything",
]


def _gating_inputs(dataset_status: DatasetStatus) -> AuthorityInputs:
    """Authority inputs with *every* gating precondition met except the dataset status."""
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=dataset_status,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        judge_calibration=None,
    )


@pytest.mark.parametrize("declared", _DECLARED_STATUSES)
def test_synthetic_forced_proposed_for_every_declared_status(declared: str) -> None:
    """A generated dataset is ``proposed`` no matter what status it claims."""
    dataset = import_synthetic_dataset("g", 3, declared_status=declared)
    assert dataset.status is DatasetStatus.PROPOSED


def test_synthetic_request_fixture_claiming_validated_is_stripped() -> None:
    """The F-4 sensitivity fixture *claims* validated; the funnel forces proposed."""
    claimed = make_synthetic_request_claiming_validated()
    assert claimed.declared_status == "validated"
    assert claimed.imported().status is DatasetStatus.PROPOSED
    # Specificity: an honestly-declared request also lands proposed (same funnel).
    assert make_synthetic_request().imported().status is DatasetStatus.PROPOSED


@pytest.mark.parametrize("n", [0, 1, 1000])
def test_synthetic_dataset_property_is_pure_proposed(n: int) -> None:
    """The ``status`` property is pure ``proposed`` regardless of example count."""
    assert SyntheticDataset(name="g", example_count=n).status is DatasetStatus.PROPOSED


def test_synthetic_status_is_a_member_of_dataset_status_enum() -> None:
    """Drift hook: the synthetic status stays a real ``DatasetStatus`` member."""
    status = SyntheticDataset(name="g", example_count=3).status
    assert status in set(DatasetStatus)
    assert status is DatasetStatus.PROPOSED


def test_synthetic_dataset_exposes_no_way_to_declare_validated() -> None:
    """Bypass fence: ``status`` is a hardwired property, never a settable field.

    Even constructing ``SyntheticDataset`` directly (bypassing the funnel) cannot
    inject a ``validated`` status — there is no ``status`` constructor argument.
    """
    field_names = {f.name for f in dataclasses.fields(SyntheticDataset)}
    assert "status" not in field_names
    assert field_names == {"name", "example_count"}
    # The property is read-only: assigning to it on a frozen dataclass must fail.
    dataset = SyntheticDataset(name="g", example_count=3)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        dataset.status = DatasetStatus.VALIDATED  # type: ignore[misc]


def test_synthetic_origin_cannot_gate_even_with_every_other_precondition_met() -> None:
    """A synthetic dataset cannot gate: its proposed status dilutes authority.

    This is the GAP-7 bypass control — it feeds a *directly constructed* synthetic
    dataset's status into the real ``resolve_authority`` path with all other gating
    preconditions satisfied, and proves the gate stays closed for a typed reason.
    """
    synthetic = SyntheticDataset(name="g", example_count=3)
    resolved = resolve_authority(_gating_inputs(synthetic.status))
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


def test_host_validated_non_synthetic_dataset_remains_eligible() -> None:
    """Specificity: a host-validated, non-synthetic dataset *can* gate.

    Same gating preconditions as the bypass control above, only the dataset is a
    host-validated (non-synthetic) one — so the gate opens. This proves the control
    is not vacuous: it is the synthetic-forced ``proposed`` status, not the rest of
    the config, that blocks gating.
    """
    resolved = resolve_authority(_gating_inputs(DatasetStatus.VALIDATED))
    assert resolved.can_gate is True
    assert resolved.reasons == []
