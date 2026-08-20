"""Diagnostic clusters — group a run's failing/non-scored items by shared cause (EG-P3; ADR 0047).

A metric that reports ``faithfulness = 0.82`` says *that* something is wrong, not *what*. Grouping
the run's ``Score``s by their shared ``Diagnostic`` ``code`` turns a flat number into an
**actionable failure mode** ("the 18% that failed are all missing-citation cases"). This is a
*different axis* from the harness explorer, which groups by call identity; here we group **failure
instances by cause**, never per source function (ADR 0037).

Two hard constraints shape this module:

* **Effect-free + pure.** Stdlib only, deterministic, and **order-invariant** — shuffling the input
  scores yields an equal result. This lets the engine store the clusters on the ``Scorecard`` while
  the anti-tamper load check (``_verify_consistency``) recomputes them from the persisted scores.
* **No ``0.0`` conflation.** A ``blocked``/``non_evaluable``/``error`` item is grouped by its
  diagnostic code and counted; it is **never** turned into a ``0.0`` value. A cluster carries a
  ``count`` and a representative ``severity``/``message``, never a score value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _as_mapping,
    _coerce_enum,
    _require,
    _require_str,
)
from evalglass.core.contracts import Diagnostic, Severity
from evalglass.core.scores import Score

#: Severity ordering for canonical cluster sorting and representative selection.
_SEVERITY_RANK: dict[Severity, int] = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


@dataclass(frozen=True)
class DiagnosticCluster:
    """One failure mode: the items of ``metric`` whose diagnostics share ``code``.

    ``count`` is the number of scores (items) that carried this code; ``severity``/``message`` are
    the code's representative (highest severity, then least message). It describes the failure
    *mode* — **which** items are the explorer's identity axis (``evalglass view --by-call``), kept
    off the cluster so the recompute is robust to a score's identity being absent. It carries **no
    value** — a non-scored item is grouped by cause, never coerced to ``0.0``.
    """

    metric: str
    code: str
    severity: Severity
    count: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "code": self.code,
            "severity": self.severity.value,
            "count": self.count,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "DiagnosticCluster")
        count = _require(m, "count", "DiagnosticCluster")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContractError("DiagnosticCluster: 'count' must be a non-negative integer")
        return cls(
            metric=_require_str(m, "metric", "DiagnosticCluster"),
            code=_require_str(m, "code", "DiagnosticCluster"),
            severity=_coerce_enum(
                Severity,
                _require(m, "severity", "DiagnosticCluster"),
                "severity",
                "DiagnosticCluster",
            ),
            count=count,
            message=_require_str(m, "message", "DiagnosticCluster"),
        )


def _outranks(candidate: Diagnostic, current: Diagnostic) -> bool:
    """Whether ``candidate`` is the better representative: higher severity, then smaller message."""
    rank_c, rank_cur = _SEVERITY_RANK[candidate.severity], _SEVERITY_RANK[current.severity]
    if rank_c != rank_cur:
        return rank_c > rank_cur
    return candidate.message < current.message


def cluster(scores: Sequence[Score]) -> list[DiagnosticCluster]:
    """Group ``scores`` into per-``(metric, code)`` failure clusters (pure, order-invariant).

    Each score contributes **once** to a ``(metric, code)`` cluster no matter how many diagnostics
    with that code it carries. The result is sorted into a canonical order — most severe, then
    largest, then ``(metric, code)`` — so two runs over the same scores (any order) produce an equal
    list, which is what makes the Scorecard field recomputable by the anti-tamper check.
    """
    reps: dict[tuple[str, str], Diagnostic] = {}
    counts: dict[tuple[str, str], int] = {}
    for score in scores:
        # Per score, keep the representative diagnostic for each code (so duplicate codes on one
        # score count the item once, and the item's representative is that code's worst diagnostic).
        per_code: dict[str, Diagnostic] = {}
        for diag in score.diagnostics:
            best = per_code.get(diag.code)
            if best is None or _outranks(diag, best):
                per_code[diag.code] = diag
        for code, diag in per_code.items():
            key = (score.metric, code)
            counts[key] = counts.get(key, 0) + 1
            rep = reps.get(key)
            if rep is None or _outranks(diag, rep):
                reps[key] = diag
    clusters = [
        DiagnosticCluster(
            metric=metric,
            code=code,
            severity=reps[(metric, code)].severity,
            count=counts[(metric, code)],
            message=reps[(metric, code)].message,
        )
        for (metric, code) in counts
    ]
    clusters.sort(key=lambda c: (-_SEVERITY_RANK[c.severity], -c.count, c.metric, c.code))
    return clusters
