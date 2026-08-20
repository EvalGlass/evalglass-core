"""Host-owned calibration + threshold approval records (EG-M4-3).

A judge metric earns the right to gate only through host-owned approval records under
``evals/calibration/*.json``: a ``CalibrationRecord`` (the judge is calibrated, with an
approver, a rationale, and variance evidence over multiple runs) and an ``ApprovedThreshold``
(value + direction + variance + approver + rationale + version). This module parses them
**fail-closed** and *derives* the ``JudgeCalibration`` + threshold approval the existing
``resolve_authority`` consumes — it never fabricates an approver or a missing field, so an
incomplete record cannot confer a gate (P8/P15).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Self

from evalglass.core import ContractError, Direction, JudgeCalibration, ThresholdApproval
from evalglass.core._validation import _as_mapping, _coerce_enum, _require, _require_str
from evalglass.harness.errors import SetupError, setup_diagnostic

_MANAGED_DIR = "_evalglass"
_MIN_VARIANCE_RUNS = 2


def _require_number(m: Any, key: str, ctx: str) -> float:
    value = _require(m, key, ctx)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ContractError(f"{ctx}: '{key}' must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{ctx}: '{key}' must be finite, got {value!r}")
    return number


def _require_int(m: Any, key: str, ctx: str) -> int:
    value = _require(m, key, ctx)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{ctx}: '{key}' must be an integer, got {value!r}")
    return value


@dataclass(frozen=True)
class CalibrationRecord:
    """Host-owned statement that a judge is calibrated, with the evidence that backs it."""

    status: JudgeCalibration
    approver: str
    rationale: str
    variance_runs: int

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "calibration") -> Self:
        m = _as_mapping(data, ctx)
        status = _coerce_enum(JudgeCalibration, _require(m, "status", ctx), "status", ctx)
        variance_runs = _require_int(m, "variance_runs", ctx)
        if variance_runs < 0:
            raise ContractError(f"{ctx}: 'variance_runs' must be non-negative")
        # A "calibrated" claim must carry real variance evidence over multiple runs (P8).
        if status is JudgeCalibration.CALIBRATED and variance_runs < _MIN_VARIANCE_RUNS:
            raise ContractError(
                f"{ctx}: a 'calibrated' judge needs variance evidence over at least "
                f"{_MIN_VARIANCE_RUNS} runs, got {variance_runs}"
            )
        return cls(
            status=status,
            approver=_require_str(m, "approver", ctx),
            rationale=_require_str(m, "rationale", ctx),
            variance_runs=variance_runs,
        )


@dataclass(frozen=True)
class ApprovedThreshold:
    """Host-owned approved gating threshold — every field is required to be approved."""

    value: float
    direction: Direction
    variance: float
    approver: str
    rationale: str
    version: str

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "threshold") -> Self:
        m = _as_mapping(data, ctx)
        variance = _require_number(m, "variance", ctx)
        if variance < 0:
            raise ContractError(f"{ctx}: 'variance' must be non-negative, got {variance}")
        return cls(
            value=_require_number(m, "value", ctx),
            direction=_coerce_enum(Direction, _require(m, "direction", ctx), "direction", ctx),
            variance=variance,
            approver=_require_str(m, "approver", ctx),
            rationale=_require_str(m, "rationale", ctx),
            version=_require_str(m, "version", ctx),
        )


@dataclass(frozen=True)
class CalibrationFile:
    """The host-owned calibration file for a judge metric: a record + optional threshold."""

    calibration: CalibrationRecord
    threshold: ApprovedThreshold | None = None

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "calibration_file") -> Self:
        m = _as_mapping(data, ctx)
        threshold_raw = m.get("threshold")
        return cls(
            calibration=CalibrationRecord.from_mapping(
                _require(m, "calibration", ctx), f"{ctx}.calibration"
            ),
            threshold=(
                ApprovedThreshold.from_mapping(threshold_raw, f"{ctx}.threshold")
                if threshold_raw is not None
                else None
            ),
        )


@dataclass(frozen=True)
class CalibrationOutcome:
    """The authority inputs a calibration file confers, fed into ``resolve_authority``."""

    judge_calibration: JudgeCalibration
    threshold_approval: ThresholdApproval
    threshold: float | None


def derive_calibration(
    file: CalibrationFile, score_range: tuple[float, float] | None, direction: Direction
) -> CalibrationOutcome:
    """Derive the authority a calibration file confers. Validates; fabricates nothing."""
    if file.threshold is None:
        # A calibrated judge with no approved threshold is informational, not a gate.
        return CalibrationOutcome(file.calibration.status, ThresholdApproval.PROPOSED, None)
    if file.threshold.direction is not direction:
        # The approver's declared direction must match the metric, or the Verdict Engine would
        # evaluate the approved threshold the wrong way — fail closed on a mismatch.
        raise ContractError(
            f"approved threshold direction {file.threshold.direction.value!r} does not match "
            f"the metric direction {direction.value!r}"
        )
    value = file.threshold.value
    if score_range is not None:
        low, high = score_range
        if not low <= value <= high:
            raise ContractError(
                f"approved threshold {value} is outside the metric score_range [{low}, {high}]"
            )
    return CalibrationOutcome(file.calibration.status, ThresholdApproval.APPROVED, value)


def load_calibration(path: str, root: Path) -> CalibrationFile:
    """Load a host-owned calibration JSON file, failing closed on path/parse errors."""
    rel = PurePosixPath(path)
    if rel.is_absolute() or ".." in rel.parts or _MANAGED_DIR in rel.parts:
        raise SetupError(
            setup_diagnostic(
                "calibration_path_invalid",
                f"calibration path {path!r} must be host-owned and within the repo",
            )
        )
    target = root / rel
    if target.is_symlink() or not target.is_file():
        raise SetupError(
            setup_diagnostic("calibration_missing", f"calibration file not found: {path}")
        )
    resolved_root = root.resolve()
    resolved = target.resolve()
    if (
        not resolved.is_relative_to(resolved_root)
        or _MANAGED_DIR in resolved.relative_to(resolved_root).parts
    ):
        raise SetupError(
            setup_diagnostic(
                "calibration_path_invalid",
                f"calibration {path!r} resolves outside the host-owned tree",
            )
        )
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SetupError(
            setup_diagnostic("calibration_unreadable", f"could not read calibration {path}: {exc}")
        ) from exc
    try:
        return CalibrationFile.from_mapping(data, "calibration_file")
    except ContractError as exc:
        raise SetupError(
            setup_diagnostic("calibration_invalid", f"calibration {path} is invalid: {exc}")
        ) from exc
