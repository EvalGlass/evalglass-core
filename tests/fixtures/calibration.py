"""F-7 — calibration-file fixtures (EG-AT0-4).

Writes a host-owned ``calibration/*.json`` record for a judge metric in a chosen
state, and **freezes the exact judge authority-reason token** each state emits.
Those tokens (``judge_uncalibrated`` / ``judge_drifted``) are not guessed: they
are verified against the real ``resolve_authority`` path in
``tests/egts/test_fixture_helpers.py`` before being trusted.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalglass.core.authority import JudgeCalibration


class CalibrationState(enum.StrEnum):
    UNCALIBRATED = "uncalibrated"
    CALIBRATING = "calibrating"
    CALIBRATED = "calibrated"
    DRIFTED = "drifted"


#: The authority-reason token each state contributes (None ⇒ the judge can gate).
#: Verified against ``resolve_authority`` in the fixture-helpers test.
_EXPECTED_REASON: dict[CalibrationState, str | None] = {
    CalibrationState.UNCALIBRATED: "judge_uncalibrated",
    CalibrationState.CALIBRATING: "judge_calibrating",
    CalibrationState.CALIBRATED: None,
    CalibrationState.DRIFTED: "judge_drifted",
}


@dataclass(frozen=True)
class CalibrationFixture:
    """A written calibration record (or none, for uncalibrated) + its expected reason."""

    state: CalibrationState
    path: Path | None
    expected_reason: str | None

    @property
    def judge_calibration(self) -> JudgeCalibration:
        return JudgeCalibration(self.state.value)


def make_calibration(
    tmp_path: Path,
    *,
    state: CalibrationState | str,
    metric: str = "faithfulness",
) -> CalibrationFixture:
    """Write a ``calibration/<metric>.json`` for ``state`` (uncalibrated writes nothing)."""
    state = _coerce(state)
    if state is CalibrationState.UNCALIBRATED:
        return CalibrationFixture(state=state, path=None, expected_reason=_EXPECTED_REASON[state])

    record: dict[str, Any] = {
        "calibration": {
            "status": state.value,
            "approver": "host:rev-1",
            "rationale": "test calibration record",
            # A "calibrated" claim must carry variance evidence over >= 2 runs.
            "variance_runs": 2 if state is CalibrationState.CALIBRATED else 0,
        }
    }
    if state is CalibrationState.CALIBRATED:
        record["threshold"] = {
            "value": 0.5,
            "direction": "higher_is_better",
            "variance": 0.01,
            "approver": "host:rev-1",
            "rationale": "approved for test",
            "version": "1",
        }
    cal_dir = tmp_path / "calibration"
    cal_dir.mkdir(parents=True, exist_ok=True)
    path = cal_dir / f"{metric}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return CalibrationFixture(state=state, path=path, expected_reason=_EXPECTED_REASON[state])


def _coerce(value: CalibrationState | str) -> CalibrationState:
    if isinstance(value, CalibrationState):
        return value
    try:
        return CalibrationState(value)
    except ValueError:
        allowed = ", ".join(s.value for s in CalibrationState)
        raise ValueError(
            f"unknown calibration state {value!r}; expected one of: {allowed}"
        ) from None


__all__ = ["CalibrationFixture", "CalibrationState", "make_calibration"]
