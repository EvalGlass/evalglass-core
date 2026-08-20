"""Tests for the computed, self-proving judge-agreement study (M7 T4, G4).

Reference kappa/agreement values are standard textbook results, not read back from
the implementation. See src/evalglass/core/agreement.py and docs/TETA_REDESIGN.md §5.
"""

from __future__ import annotations

import hashlib
import math

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.agreement import (
    Confusion,
    JudgeAgreementStudy,
    cohen_kappa,
    percent_agreement,
)
from evalglass.core.authority import JudgeCalibration


def _d(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _study(**over: object) -> JudgeAgreementStudy:
    base: dict[str, object] = {
        "confusion": Confusion(tp=3, fp=0, fn=0, tn=3),
        "judge_instrument_sha256": _d("judge"),
        "rubric_sha256": _d("rubric"),
        "variance_runs": 3,
        "protocol_version": "dafo-hybrid-v1",
        "approver": "reviewer@example.com",
        "rationale": "6 matched items, perfect agreement",
    }
    base.update(over)
    return JudgeAgreementStudy.compute(**base)  # type: ignore[arg-type]


# --- statistics ------------------------------------------------------------


def test_perfect_agreement() -> None:
    c = Confusion(tp=3, fp=0, fn=0, tn=3)
    assert percent_agreement(c) == 1.0
    assert math.isclose(cohen_kappa(c), 1.0)


def test_chance_level_kappa_zero() -> None:
    c = Confusion(tp=1, fp=1, fn=1, tn=1)
    assert percent_agreement(c) == 0.5
    assert math.isclose(cohen_kappa(c), 0.0, abs_tol=1e-9)


def test_degenerate_single_class_returns_one() -> None:
    c = Confusion(tp=6, fp=0, fn=0, tn=0)  # expected agreement == 1
    assert cohen_kappa(c) == 1.0


# --- Confusion invariants --------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tp": -1, "fp": 0, "fn": 0, "tn": 1},
        {"tp": True, "fp": 0, "fn": 0, "tn": 1},
        {"tp": 0, "fp": 0, "fn": 0, "tn": 0},  # empty
    ],
)
def test_confusion_rejects_bad(kwargs: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        Confusion(**kwargs)  # type: ignore[arg-type]


# --- self-proving arithmetic ----------------------------------------------


def test_compute_builds_matching_summaries() -> None:
    s = _study()
    assert s.percent_agreement == 1.0
    assert math.isclose(s.kappa, 1.0)


def test_construct_with_contradictory_agreement_rejected() -> None:
    with pytest.raises(ContractError):
        JudgeAgreementStudy(
            judge_instrument_sha256=_d("j"),
            rubric_sha256=_d("r"),
            confusion=Confusion(tp=3, fp=0, fn=0, tn=3),
            percent_agreement=0.5,  # contradicts (real is 1.0)
            kappa=1.0,
            variance_runs=3,
            protocol_version="v1",
        )


def test_construct_with_contradictory_kappa_rejected() -> None:
    with pytest.raises(ContractError):
        JudgeAgreementStudy(
            judge_instrument_sha256=_d("j"),
            rubric_sha256=_d("r"),
            confusion=Confusion(tp=1, fp=1, fn=1, tn=1),
            percent_agreement=0.5,
            kappa=0.9,  # contradicts (real is 0.0)
            variance_runs=3,
            protocol_version="v1",
        )


def test_bad_digest_rejected() -> None:
    with pytest.raises(ContractError):
        _study(judge_instrument_sha256="not-a-digest")


# --- calibration status ----------------------------------------------------


def test_uncalibrated_without_approver() -> None:
    s = _study(approver=None)
    assert (
        s.calibration_status(
            current_instrument_sha256=_d("judge"), current_rubric_sha256=_d("rubric")
        )
        is JudgeCalibration.UNCALIBRATED
    )


def test_uncalibrated_below_variance_floor() -> None:
    s = _study(variance_runs=1)
    assert (
        s.calibration_status(
            current_instrument_sha256=_d("judge"), current_rubric_sha256=_d("rubric")
        )
        is JudgeCalibration.UNCALIBRATED
    )


def test_drifted_when_instrument_changes() -> None:
    s = _study()
    assert (
        s.calibration_status(
            current_instrument_sha256=_d("judge-v2"), current_rubric_sha256=_d("rubric")
        )
        is JudgeCalibration.DRIFTED
    )


def test_drifted_when_rubric_changes() -> None:
    s = _study()
    assert (
        s.calibration_status(
            current_instrument_sha256=_d("judge"), current_rubric_sha256=_d("rubric-v2")
        )
        is JudgeCalibration.DRIFTED
    )


def test_calibrated_when_approved_and_matching() -> None:
    s = _study()
    assert (
        s.calibration_status(
            current_instrument_sha256=_d("judge"), current_rubric_sha256=_d("rubric")
        )
        is JudgeCalibration.CALIBRATED
    )


# --- serialization ---------------------------------------------------------


def test_round_trip() -> None:
    s = _study()
    assert JudgeAgreementStudy.from_dict(s.to_dict()) == s


def test_from_dict_reverifies_arithmetic() -> None:
    # A hand-edited study whose stored agreement contradicts its confusion won't load.
    d = _study().to_dict()
    d["percent_agreement"] = 0.5
    with pytest.raises(ContractError):
        JudgeAgreementStudy.from_dict(d)
