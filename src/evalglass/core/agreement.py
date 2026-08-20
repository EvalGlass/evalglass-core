"""Computed, self-proving judge-agreement study (M7 T4, G4).

Alpha's calibration was *declared*: a host asserted ``status: calibrated`` and the
only quantitative check was ``variance_runs >= 2``. There were no raw ratings, no
confusion counts, no agreement statistic — so authority could rest on an unverified
claim. This module makes the study a *computed* object whose arithmetic proves
itself: percent agreement and Cohen's kappa are recomputed from the confusion table
on construction and must match the stored values, and every count/range is validated
(the beta-improved A22 lesson, generalized into a study).

A study also binds the **instrument identity** (judge + rubric digests) it was run
against, so a changed judge or rubric resolves as ``drifted`` — old labels cannot
silently calibrate a new measurement instrument (a real LLM->hybrid judge swap, A23).

Effect-free, stdlib-only (``math`` + ``hashlib`` surface only via digests supplied by
the harness). The core computes and verifies; the harness loads the host file and the
human approves. See ``docs/TETA_REDESIGN.md`` §5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import ContractError, _as_mapping, _require, _require_str
from evalglass.core.authority import JudgeCalibration

_TOL = 1e-4
_MIN_VARIANCE_RUNS = 2
_HEX = frozenset("0123456789abcdef")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in _HEX for c in value)


@dataclass(frozen=True)
class Confusion:
    """A 2x2 confusion table of judge vs human gold over binary decisions."""

    tp: int
    fp: int
    fn: int
    tn: int

    def __post_init__(self) -> None:
        for name in ("tp", "fp", "fn", "tn"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ContractError(f"Confusion.{name} must be a non-negative integer")
        if self.n_items == 0:
            raise ContractError("Confusion must count at least one item")

    @property
    def n_items(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Confusion")
        vals: dict[str, int] = {}
        for name in ("tp", "fp", "fn", "tn"):
            v = _require(m, name, "Confusion")
            if isinstance(v, bool) or not isinstance(v, int):
                raise ContractError(f"Confusion.{name} must be an integer")
            vals[name] = v
        return cls(**vals)


def percent_agreement(c: Confusion) -> float:
    """Observed proportion of items where judge and gold agree."""
    return (c.tp + c.tn) / c.n_items


def cohen_kappa(c: Confusion) -> float:
    """Cohen's kappa; the degenerate ``expected agreement == 1`` case returns 1.0."""
    n = c.n_items
    po = (c.tp + c.tn) / n
    pe = ((c.tp + c.fp) * (c.tp + c.fn) + (c.fn + c.tn) * (c.fp + c.tn)) / (n * n)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


@dataclass(frozen=True)
class JudgeAgreementStudy:
    """A computed judge-vs-gold study, bound to the instrument it measured.

    ``percent_agreement`` and ``kappa`` are recomputed from ``confusion`` and must match
    the stored values (self-proving). The study is *not* authority on its own: a human
    ``approver`` + a matching current instrument/rubric is what earns ``calibrated``.
    """

    judge_instrument_sha256: str
    rubric_sha256: str
    confusion: Confusion
    percent_agreement: float
    kappa: float
    variance_runs: int
    protocol_version: str
    approver: str | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        for name in ("judge_instrument_sha256", "rubric_sha256"):
            if not _is_sha256(getattr(self, name)):
                raise ContractError(f"JudgeAgreementStudy.{name} must be a 64-char hex sha256")
        if not (0.0 <= self.percent_agreement <= 1.0):
            raise ContractError("percent_agreement must be in [0, 1]")
        if not (-1.0 <= self.kappa <= 1.0):
            raise ContractError("kappa must be in [-1, 1]")
        # Self-proving arithmetic: the stored summaries must match the confusion table.
        if abs(self.percent_agreement - percent_agreement(self.confusion)) > _TOL:
            raise ContractError("percent_agreement contradicts the confusion table")
        if abs(self.kappa - cohen_kappa(self.confusion)) > _TOL:
            raise ContractError("kappa contradicts the confusion table")
        if isinstance(self.variance_runs, bool) or not isinstance(self.variance_runs, int):
            raise ContractError("variance_runs must be an int")
        if self.variance_runs < 0:
            raise ContractError("variance_runs must be non-negative")
        if not self.protocol_version.strip():
            raise ContractError("protocol_version must be a non-empty string")
        for name in ("approver", "rationale"):
            v = getattr(self, name)
            if v is not None and not v.strip():
                raise ContractError(f"JudgeAgreementStudy.{name}, if present, must be non-empty")

    @classmethod
    def compute(
        cls,
        *,
        confusion: Confusion,
        judge_instrument_sha256: str,
        rubric_sha256: str,
        variance_runs: int,
        protocol_version: str,
        approver: str | None = None,
        rationale: str | None = None,
    ) -> Self:
        """Build a study by *computing* the summaries from the confusion table."""
        return cls(
            judge_instrument_sha256=judge_instrument_sha256,
            rubric_sha256=rubric_sha256,
            confusion=confusion,
            percent_agreement=percent_agreement(confusion),
            kappa=cohen_kappa(confusion),
            variance_runs=variance_runs,
            protocol_version=protocol_version,
            approver=approver,
            rationale=rationale,
        )

    def calibration_status(
        self, *, current_instrument_sha256: str, current_rubric_sha256: str
    ) -> JudgeCalibration:
        """Resolve this study against the current run's instrument + rubric.

        ``uncalibrated`` without a human approver; ``drifted`` if the judge instrument
        or rubric changed since approval; ``calibrated`` only when approved *and* the
        instrument + rubric still match *and* the study met the variance floor.
        """
        if self.approver is None:
            return JudgeCalibration.UNCALIBRATED
        if self.variance_runs < _MIN_VARIANCE_RUNS:
            return JudgeCalibration.UNCALIBRATED
        if (
            self.judge_instrument_sha256 != current_instrument_sha256
            or self.rubric_sha256 != current_rubric_sha256
        ):
            return JudgeCalibration.DRIFTED
        return JudgeCalibration.CALIBRATED

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "judge_instrument_sha256": self.judge_instrument_sha256,
            "rubric_sha256": self.rubric_sha256,
            "confusion": self.confusion.to_dict(),
            "percent_agreement": self.percent_agreement,
            "kappa": self.kappa,
            "variance_runs": self.variance_runs,
            "protocol_version": self.protocol_version,
        }
        if self.approver is not None:
            out["approver"] = self.approver
        if self.rationale is not None:
            out["rationale"] = self.rationale
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "JudgeAgreementStudy")
        return cls(
            judge_instrument_sha256=_require_str(
                m, "judge_instrument_sha256", "JudgeAgreementStudy"
            ),
            rubric_sha256=_require_str(m, "rubric_sha256", "JudgeAgreementStudy"),
            confusion=Confusion.from_dict(
                _as_mapping(_require(m, "confusion", "JudgeAgreementStudy"), "confusion")
            ),
            percent_agreement=_num(m, "percent_agreement"),
            kappa=_num(m, "kappa"),
            variance_runs=_int(m, "variance_runs"),
            protocol_version=_require_str(m, "protocol_version", "JudgeAgreementStudy"),
            approver=_opt_nonempty(m, "approver"),
            rationale=_opt_nonempty(m, "rationale"),
        )


def _num(m: Mapping[str, Any], key: str) -> float:
    v = _require(m, key, "JudgeAgreementStudy")
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ContractError(f"JudgeAgreementStudy.{key} must be a number")
    return float(v)


def _int(m: Mapping[str, Any], key: str) -> int:
    v = _require(m, key, "JudgeAgreementStudy")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ContractError(f"JudgeAgreementStudy.{key} must be an int")
    return v


def _opt_nonempty(m: Mapping[str, Any], key: str) -> str | None:
    v = m.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ContractError(f"JudgeAgreementStudy.{key}, if present, must be a non-empty string")
    return v
