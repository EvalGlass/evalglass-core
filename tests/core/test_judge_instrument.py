"""Tests for judge instrument identity (M7 G9).

A judge that changes provider/seed/temperature/prompt/rubric must change its digest,
so old agreement labels cannot silently calibrate a new instrument.
See src/evalglass/core/judge_instrument.py and docs/TETA_REDESIGN.md §5.
"""

from __future__ import annotations

import hashlib

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.judge_instrument import JudgeInstrument


def _d(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _inst(**over: object) -> JudgeInstrument:
    base: dict[str, object] = {
        "provider": "openrouter",
        "model": "openai/gpt-5-mini",
        "prompt_sha256": _d("prompt"),
        "rubric_sha256": _d("rubric"),
        "parser_version": "v2",
        "seed": 7,
        "temperature": 0.0,
    }
    base.update(over)
    return JudgeInstrument(**base)  # type: ignore[arg-type]


def test_digest_is_stable() -> None:
    assert _inst().digest() == _inst().digest()


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "azure"},
        {"model": "openai/gpt-5"},
        {"prompt_sha256": _d("prompt-v2")},
        {"rubric_sha256": _d("rubric-v2")},
        {"parser_version": "v3"},
        {"seed": 8},
        {"temperature": 0.7},
        {"decoding": {"top_p": 0.9}},
    ],
)
def test_any_field_change_moves_the_digest(change: dict[str, object]) -> None:
    assert _inst().digest() != _inst(**change).digest()


def test_prompt_content_digest_not_a_ref() -> None:
    # Two judges with the same prompt *name* but different resolved text differ —
    # the identity is the content digest, not a reference string.
    a = _inst(prompt_sha256=_d("You are a strict grader. v1"))
    b = _inst(prompt_sha256=_d("You are a strict grader. v2"))
    assert a.digest() != b.digest()


def test_round_trip_full() -> None:
    inst = _inst(decoding={"top_p": 0.9, "max_tokens": 512})
    assert JudgeInstrument.from_dict(inst.to_dict()) == inst


def test_round_trip_minimal() -> None:
    inst = JudgeInstrument(
        provider="p", model="m", prompt_sha256=_d("p"), rubric_sha256=_d("r"), parser_version="1"
    )
    assert JudgeInstrument.from_dict(inst.to_dict()) == inst


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provider": "  "},
        {"model": ""},
        {"prompt_sha256": "nothex"},
        {"seed": True},
        {"temperature": float("inf")},
    ],
)
def test_invalid_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        _inst(**kwargs)


def test_digest_feeds_agreement_study_drift() -> None:
    # The instrument digest is exactly what a JudgeAgreementStudy binds for drift.
    from evalglass.core.agreement import Confusion, JudgeAgreementStudy
    from evalglass.core.authority import JudgeCalibration

    inst = _inst()
    study = JudgeAgreementStudy.compute(
        confusion=Confusion(tp=3, fp=0, fn=0, tn=3),
        judge_instrument_sha256=inst.digest(),
        rubric_sha256=inst.rubric_sha256,
        variance_runs=3,
        protocol_version="v1",
        approver="reviewer",
    )
    assert (
        study.calibration_status(
            current_instrument_sha256=inst.digest(), current_rubric_sha256=inst.rubric_sha256
        )
        is JudgeCalibration.CALIBRATED
    )
    changed = _inst(temperature=0.7)
    assert (
        study.calibration_status(
            current_instrument_sha256=changed.digest(), current_rubric_sha256=changed.rubric_sha256
        )
        is JudgeCalibration.DRIFTED
    )
