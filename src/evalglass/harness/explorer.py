"""Read-only metrics explorer (EG-H4-1/EG-H4-3; alignment plan §5.7, delta D5).

A read-only **view** over typed product artifacts (``runrecord.json`` / ``scorecard.json``). It is
NOT a lane and NOT a meaning engine:

- **Typed-only / no recompute.** It loads artifacts through the contract parsers
  (:meth:`RunRecord.from_dict`) and reads typed fields; it imports no Verdict Engine, authority
  resolver, or aggregator, and it echoes the Scorecard verdict **verbatim** — it never re-derives a
  verdict, authority, or aggregate.
- **Grouped by explicit identity.** Score rows are grouped by ``(example_id, unit_id)`` — never by
  list order. A score that lacks explicit identity is diagnosed and excluded, never guessed; there
  is no per-source-function attribution.
- **Honest non-scored display.** A non-scored / invalid row shows ``value=None`` (rendered ``-``),
  never ``0.0``.
- **No effects.** Stdlib only — no network, provider, or external-process access; writes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evalglass.core.results import RunRecord
from evalglass.core.scores import ScoreStatus, Validity


class ExplorerError(ValueError):
    """A malformed/unreadable artifact — fail closed (never a partial or guessed view)."""


@dataclass(frozen=True)
class MetricRow:
    """One metric outcome for a subject. ``value`` is ``None`` for any non-scored/invalid row.

    ``status`` **and** ``validity`` are both carried so a null value is honestly explained — a
    ``scored``/``invalid`` row reads as exactly that, never as a silent ``scored`` with a missing
    number — and any diagnostic codes (why a row blocked/errored) travel with it.
    """

    metric: str
    status: str
    validity: str
    value: float | None
    diagnostics: list[str] = field(default_factory=list)
    #: The metric's already-resolved authority (``{can_gate, level, blocked, reasons}``), read
    #: verbatim from the Scorecard — the trust context for the value, never recomputed here.
    authority: dict[str, Any] | None = None

    @property
    def display_value(self) -> str:
        """The render-safe value: ``-`` for a non-scored row, never ``0.0`` (CLAUDE.md §9)."""
        return "-" if self.value is None else format(self.value, "g")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "status": self.status,
            "validity": self.validity,
            "value": self.value,
        }
        if self.diagnostics:
            out["diagnostics"] = list(self.diagnostics)
        if self.authority is not None:
            out["authority"] = dict(self.authority)
        return out


@dataclass(frozen=True)
class SubjectGroup:
    """The metric rows measured for one evaluated subject, keyed by explicit identity."""

    example_id: str
    unit_id: str | None
    rows: list[MetricRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "unit_id": self.unit_id,
            "rows": [r.to_dict() for r in self.rows],
        }


@dataclass(frozen=True)
class ExplorerView:
    """A read-only view of a run: the echoed verdict plus per-subject metric rows."""

    run_id: str
    verdict: str
    ci_should_fail: bool
    subjects: list[SubjectGroup]
    diagnostics: list[str] = field(default_factory=list)
    #: The run's baseline comparability state (read from the Scorecard), or ``None`` if absent —
    #: so a value is never shown as a regression without its comparability context.
    baseline_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "verdict": self.verdict,
            "ci_should_fail": self.ci_should_fail,
            "baseline_state": self.baseline_state,
            "subjects": [s.to_dict() for s in self.subjects],
            "diagnostics": list(self.diagnostics),
        }


def read_run_record(path: Path) -> RunRecord:
    """Load + parse a ``runrecord.json`` through the contract parser (fail-closed).

    An unreadable file, invalid JSON, or a structurally-malformed artifact is an
    :class:`ExplorerError` — never a partial view. Old artifacts without ``lane_results`` parse
    (the contract parser defaults the missing side channel to ``[]``).
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ExplorerError(f"could not read artifact {path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ExplorerError(f"artifact {path} is not valid JSON: {exc}") from exc
    try:
        # ContractError is a ValueError; any structural defect fails closed here.
        return RunRecord.from_dict(raw)
    except ValueError as exc:
        raise ExplorerError(f"malformed run record {path}: {exc}") from exc


def build_view(record: RunRecord) -> ExplorerView:
    """Group the run's scores by explicit subject identity and echo the verdict verbatim."""
    groups: dict[tuple[str, str | None], list[MetricRow]] = {}
    diagnostics: list[str] = []
    # Already-resolved authority, keyed by metric, read verbatim from the Scorecard — the trust
    # context for each value (it is read, never recomputed here).
    authority_by_metric = record.scorecard.authority
    for score in record.scores:
        if not score.example_id:
            diagnostics.append(
                f"metric {score.metric!r} has a score with no example_id; not grouped "
                "(subject identity is never guessed from list order)"
            )
            continue
        # Only a scored + valid measurement carries a value; everything else is None, never 0.0.
        meaningful = score.status is ScoreStatus.SCORED and score.validity is Validity.VALID
        resolved = authority_by_metric.get(score.metric)
        row = MetricRow(
            metric=score.metric,
            status=score.status.value,
            validity=score.validity.value,
            value=score.value if meaningful else None,
            diagnostics=[d.code for d in score.diagnostics],
            authority=resolved.to_dict() if resolved is not None else None,
        )
        groups.setdefault((score.example_id, score.unit_id), []).append(row)
    subjects = [
        SubjectGroup(
            example_id=example_id,
            unit_id=unit_id,
            rows=sorted(rows, key=lambda r: r.metric),
        )
        for (example_id, unit_id), rows in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
        )
    ]
    verdict = record.scorecard.verdict
    baseline = record.scorecard.baseline_state
    return ExplorerView(
        run_id=record.run_id,
        verdict=verdict.verdict.value,
        ci_should_fail=verdict.ci_should_fail,
        subjects=subjects,
        diagnostics=diagnostics,
        baseline_state=baseline.value if baseline is not None else None,
    )


def explore(path: Path) -> ExplorerView:
    """Read a ``runrecord.json`` artifact and build its read-only view."""
    return build_view(read_run_record(path))
