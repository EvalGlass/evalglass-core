"""Provenance fingerprints + baseline comparability (EG-M0-4b).

A score without provenance is uninterpretable; a regression without comparability
is not a claim (``CLAUDE.md §11``). A run is fingerprinted across structured
dimensions; a regression may only be claimed when the current and baseline runs
are *comparable* — otherwise the state is non_comparable / missing_baseline /
comparison_not_requested, and EvalGlass must not manufacture a regression.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.contracts import ContractError
from evalglass.core.provenance import (
    REQUIRED_DIMENSIONS,
    BaselineState,
    ComparableRunFingerprint,
    RunFingerprint,
    fingerprint_dimension,
)


def _dims(**over: object) -> dict[str, object]:
    base: dict[str, object] = {dim: f"{dim}-v1" for dim in REQUIRED_DIMENSIONS}
    base.update(over)
    return base


# --- fingerprint primitive --------------------------------------------------


def test_fingerprint_is_deterministic_and_sensitive() -> None:
    assert fingerprint_dimension({"a": 1, "b": 2}) == fingerprint_dimension({"b": 2, "a": 1})
    assert fingerprint_dimension({"a": 1}) != fingerprint_dimension({"a": 2})


def test_run_fingerprint_requires_all_dimensions() -> None:
    incomplete = _dims()
    del incomplete["dataset"]
    with pytest.raises(ContractError):
        RunFingerprint.of(incomplete)


def test_run_fingerprint_round_trips() -> None:
    fp = RunFingerprint.of(_dims())
    assert RunFingerprint.from_dict(json.loads(json.dumps(fp.to_dict()))) == fp


# --- comparability ----------------------------------------------------------


def test_comparable_when_gating_dimensions_match() -> None:
    fp = RunFingerprint.of(_dims())
    cmp = ComparableRunFingerprint(current=fp, baseline=fp, requested=True)
    assert cmp.state is BaselineState.COMPARABLE
    assert cmp.can_support_regression is True
    assert cmp.changed_dimensions == []


def test_not_comparable_when_a_gating_dimension_changed() -> None:
    current = RunFingerprint.of(_dims(dataset="dataset-v2"))
    baseline = RunFingerprint.of(_dims(dataset="dataset-v1"))
    cmp = ComparableRunFingerprint(current=current, baseline=baseline, requested=True)
    assert cmp.state is BaselineState.NOT_COMPARABLE
    assert cmp.can_support_regression is False
    assert "dataset" in cmp.changed_dimensions


def test_non_gating_change_stays_comparable() -> None:
    # 'example' is not a gating dimension: different examples still compare.
    current = RunFingerprint.of(_dims(example="example-v2"))
    baseline = RunFingerprint.of(_dims(example="example-v1"))
    cmp = ComparableRunFingerprint(current=current, baseline=baseline, requested=True)
    assert cmp.state is BaselineState.COMPARABLE


def test_missing_baseline() -> None:
    cmp = ComparableRunFingerprint(
        current=RunFingerprint.of(_dims()), baseline=None, requested=True
    )
    assert cmp.state is BaselineState.MISSING_BASELINE
    assert cmp.can_support_regression is False


def test_comparison_not_requested() -> None:
    fp = RunFingerprint.of(_dims())
    cmp = ComparableRunFingerprint(current=fp, baseline=fp, requested=False)
    assert cmp.state is BaselineState.COMPARISON_NOT_REQUESTED
    assert cmp.can_support_regression is False


def test_missing_gating_dimension_is_not_comparable() -> None:
    """A gating dimension absent from the fingerprints must fail closed, not pass."""
    fp = RunFingerprint.of(_dims())
    cmp = ComparableRunFingerprint(
        current=fp, baseline=fp, requested=True, gating_dimensions=["misspelled_dim"]
    )
    assert cmp.state is BaselineState.NOT_COMPARABLE
    assert "misspelled_dim" in cmp.changed_dimensions
    assert cmp.can_support_regression is False


def test_non_json_dimension_fails_closed() -> None:
    """A non-JSON dimension value (e.g. a set) must raise, not hash an unstable repr."""
    with pytest.raises(ContractError):
        fingerprint_dimension({"items": {1, 2, 3}})
    with pytest.raises(ContractError):
        RunFingerprint.of(_dims(config={1, 2, 3}))


def test_malformed_baseline_payload_fails() -> None:
    """A present-but-wrong-shaped baseline must raise, not be read as missing_baseline."""
    payload = ComparableRunFingerprint(
        current=RunFingerprint.of(_dims()), baseline=None, requested=True
    ).to_dict()
    payload["baseline"] = "corrupt-not-a-fingerprint"
    with pytest.raises(ContractError):
        ComparableRunFingerprint.from_dict(payload)


def test_comparable_fingerprint_round_trips() -> None:
    current = RunFingerprint.of(_dims(dataset="dataset-v2"))
    baseline = RunFingerprint.of(_dims())
    cmp = ComparableRunFingerprint(current=current, baseline=baseline, requested=True)
    assert ComparableRunFingerprint.from_dict(json.loads(json.dumps(cmp.to_dict()))) == cmp
