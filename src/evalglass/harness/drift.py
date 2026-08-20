"""Continuous drift evaluation — the first production consumer of ``comparison.py`` (EG-P4).

Quality erodes silently: a provider updates, a prompt tweak lands, retrieval degrades, and you find
out weeks later. teta could answer *"is it worse than baseline?"* only when a human ran a
comparison. This module is the honest, opt-in bridge: given a current run and its baseline, it
them into :func:`~evalglass.core.comparison.paired_comparison` and reports drift **honoring
comparability**.

Two invariants shape it (mirroring the ``LaneResult`` "evidence, not authority" shape):

* **No second verdict path.** A :class:`DriftResult` carries **no** verdict, exit, or authority.
  A regression is a typed label + an explanatory :class:`~evalglass.core.contracts.Diagnostic`
  (INFO/WARNING), never a ``Verdict``. If a regression *should* fail CI, that flows through the
  Verdict Engine on a ``comparable`` baseline — not through drift.
* **Honesty of the signal.** A ``regression`` label is licensed **only** when the runs are
  ``comparable`` (``BaselineState.COMPARABLE``) *and* the paired interval clears zero (the classify
  rule, reused — never re-implemented). A delta inside the interval is ``within_noise``;
  ``not_comparable``/``missing_baseline`` is reported as exactly that, never as "no regression".

This module is a harness consumer: the comparison math is effect-free Core; the re-run, filesystem,
and clock live in the harness (the ``watch`` command). It never writes the baseline.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self

from evalglass.adapters.result_store_fs import atomic_write_text
from evalglass.core._validation import (
    _as_mapping,
    _coerce_enum,
    _opt_str_list,
    _require,
)
from evalglass.core.comparison import (
    ComparisonResult,
    DeltaOutcome,
    PairedComparison,
    build_comparison,
)
from evalglass.core.contracts import Diagnostic, Severity
from evalglass.core.provenance import BaselineState
from evalglass.core.registry import Direction
from evalglass.core.results import RunRecord, Scorecard

#: The BaselineStates under which a paired comparison can run and license a regression label.
_COMPARABLE = BaselineState.COMPARABLE


class Comparability(enum.StrEnum):
    """Whether a drift check could honestly compare the current run to its baseline."""

    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not_comparable"
    MISSING_BASELINE = "missing_baseline"


#: Map the primary comparison state to the drift-sidecar comparability (fail-closed to missing).
_COMPARABILITY_OF_STATE: dict[BaselineState, Comparability] = {
    BaselineState.COMPARABLE: Comparability.COMPARABLE,
    BaselineState.NOT_COMPARABLE: Comparability.NOT_COMPARABLE,
    BaselineState.MISSING_BASELINE: Comparability.MISSING_BASELINE,
    BaselineState.COMPARISON_NOT_REQUESTED: Comparability.MISSING_BASELINE,
}


@dataclass(frozen=True)
class DriftResult:
    """A run's drift against its baseline — evidence, never authority.

    Deliberately carries **no** verdict / exit / authority field: a drift check informs, it never
    decides. ``comparison`` is the paired per-metric deltas (present only when ``comparable``);
    ``skipped_metrics`` are metrics with no declared direction (compared to nothing, never crashed).
    """

    comparability: Comparability
    comparison: PairedComparison | None = None
    skipped_metrics: list[str] = field(default_factory=list)

    @classmethod
    def from_comparison_result(cls, result: ComparisonResult) -> Self:
        """Project the primary D4 comparison into the drift sidecar view (one shared computation).

        The drift artifact is a compatibility rendering of the same typed comparison the Scorecard
        carries — it forks no math. ``comparable`` keeps the paired deltas; other states carry
        none, exactly as the primary contract requires.
        """
        comparability = _COMPARABILITY_OF_STATE.get(result.state, Comparability.MISSING_BASELINE)
        return cls(
            comparability=comparability,
            comparison=result.comparison,
            skipped_metrics=list(result.skipped_metrics),
        )

    def regressions(self) -> list[str]:
        """Metrics honestly labeled a regression — empty unless the runs are comparable."""
        if self.comparability is not Comparability.COMPARABLE or self.comparison is None:
            return []
        return sorted(
            m for m, d in self.comparison.deltas.items() if d.outcome is DeltaOutcome.REGRESSION
        )

    def diagnostic(self) -> Diagnostic:
        """An explanatory diagnostic (INFO/WARNING) after the verdict; changes nothing."""
        if self.comparability is Comparability.MISSING_BASELINE:
            return Diagnostic(
                code="drift.missing_baseline",
                severity=Severity.INFO,
                message="no baseline to compare against; drift not evaluated",
            )
        if self.comparability is Comparability.NOT_COMPARABLE:
            return Diagnostic(
                code="drift.not_comparable",
                severity=Severity.INFO,
                message="current run is not comparable to the baseline; no regression claim made",
            )
        regressed = self.regressions()
        if regressed:
            return Diagnostic(
                code="drift.regression",
                severity=Severity.WARNING,
                message=f"comparable regression on: {', '.join(regressed)}",
                details={"metrics": list(regressed)},
            )
        return Diagnostic(
            code="drift.no_comparable_regression",
            severity=Severity.INFO,
            message="no comparable regression found (this does not mean quality is fine)",
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"comparability": self.comparability.value}
        if self.comparison is not None:
            out["comparison"] = self.comparison.to_dict()
        if self.skipped_metrics:
            out["skipped_metrics"] = list(self.skipped_metrics)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "DriftResult")
        comparison_raw = m.get("comparison")
        return cls(
            comparability=_coerce_enum(
                Comparability,
                _require(m, "comparability", "DriftResult"),
                "comparability",
                "DriftResult",
            ),
            comparison=(
                PairedComparison.from_dict(_as_mapping(comparison_raw, "DriftResult.comparison"))
                if comparison_raw is not None
                else None
            ),
            skipped_metrics=_opt_str_list(m, "skipped_metrics", "DriftResult"),
        )


def evaluate_drift(
    current: RunRecord, baseline: RunRecord | None, directions: Mapping[str, Direction]
) -> DriftResult:
    """Evaluate the current run's drift against its baseline, honoring comparability (EG-P4-1).

    Delegates to the single :func:`~evalglass.core.comparison.build_comparison` the primary D4
    Scorecard comparison also uses, then projects the typed result into the drift sidecar view — so
    the ``watch`` and ``run`` comparison semantics cannot diverge. A regression is emitted only when
    the runs are ``comparable``; a metric with no declared direction is **skipped**, never a crash.
    Returns evidence only — no verdict, exit, or authority.
    """
    state = current.scorecard.baseline_state or BaselineState.MISSING_BASELINE
    result = build_comparison(
        current_scores=current.scores,
        baseline_scores=baseline.scores if baseline is not None else None,
        baseline_run_id=baseline.run_id if baseline is not None else None,
        state=state,
        directions=directions,
    )
    return DriftResult.from_comparison_result(result)


def persist_drift(result: DriftResult, run_dir: Path) -> Path:
    """Write the typed drift artifact to ``run_dir/drift.json`` crash-safely (EG-P4-2).

    Reuses the result store's atomic writer; ``run_dir`` is the already-validated, root-bounded run
    directory the store persisted the run into, so no new unsafe write path is introduced. This
    **never** touches the baseline file.
    """
    path = run_dir / "drift.json"
    atomic_write_text(path, json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def with_drift_diagnostic(scorecard: Scorecard, result: DriftResult) -> Scorecard:
    """Append the drift's explanatory diagnostic to the Scorecard, changing nothing else (EG-P4-2).

    Mirrors how route diagnostics ride *after* the verdict: the verdict, ``ci_should_fail``,
    metrics, authority, estimates, and clusters are untouched — only ``diagnostics`` grows by one
    entry. Diagnostics are not recomputed by the anti-tamper check, so the record still loads.
    """
    return replace(scorecard, diagnostics=[*scorecard.diagnostics, result.diagnostic()])
