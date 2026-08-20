"""Score sinks — Markdown + terminal renderings of a Scorecard (EG-M1-5).

A report is a *rendering* of the typed ``Scorecard``: the verdict word, the CI meaning, the
per-metric aggregates + authority explanation, the baseline state, and diagnostics all come
straight from scorecard fields. These sinks never recompute the verdict or authority, and the
headline verdict text is derived from ``scorecard.verdict.verdict`` — so a report can never
claim more authority than the run holds (build contract §9; CLAUDE.md §11). The CLI writes the
returned string to ``report.md`` / stdout; the sinks themselves perform no I/O.
"""

from __future__ import annotations

from evalglass.core import AggregatedMetric, Scorecard, Verdict
from evalglass.core.comparison import ComparisonResult
from evalglass.core.provenance import BaselineState

_VERDICT_DESC: dict[Verdict, str] = {
    Verdict.INFORMATIONAL: "no active gate — this run does not assert pass/fail quality",
    Verdict.PASS: "every active gate passed its approved threshold",
    Verdict.FAIL: "an active gate is validly measured below its approved threshold",
    Verdict.BLOCKED: "an active gate cannot make an honest quality claim",
}


def gate_state(scorecard: Scorecard, metric: str) -> str:
    """A metric's gate state, read from the Verdict Engine's typed gate lists (never recomputed).

    Labels come from the ``Verdict`` enum so no verdict token is hardcoded. Public so the CI
    annotation sink renders the same gate state without duplicating this logic.
    """
    payload = scorecard.verdict
    if metric in payload.blocked_gates:
        return Verdict.BLOCKED.value
    if metric in payload.failing_gates:
        return Verdict.FAIL.value
    if metric in payload.passing_gates:
        return Verdict.PASS.value
    return Verdict.INFORMATIONAL.value


def _value(value: float | None) -> str:
    return "—" if value is None else f"{value:.4g}"


def _count(value: int | None) -> str:
    """A population count cell — an unknown (plan-derived) pre-effect count renders as ``?``."""
    return "?" if value is None else str(value)


def _evaluability_lines(scorecard: Scorecard) -> list[str]:
    """The Evaluability table — per-metric coverage rendered from the typed PopulationSummary."""
    lines = [
        "",
        "## Evaluability",
        "",
        "| Metric | Available | Eligible | Scored | Non-evaluable | Blocked | Error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {pop.metric} | {_count(pop.available)} | {_count(pop.eligible)} | "
        f"{pop.scored_valid} | {pop.non_evaluable} | {pop.blocked} | {pop.error} |"
        for pop in scorecard.populations
    ]
    return lines


class MarkdownScoreSink:
    """Render a Scorecard as a Markdown report."""

    def render(self, scorecard: Scorecard) -> str:
        payload = scorecard.verdict
        ci = "exit non-zero" if payload.ci_should_fail else "exit zero"
        lines = [
            "# EvalGlass Scorecard",
            "",
            f"**Verdict:** {payload.verdict.value} — {_VERDICT_DESC[payload.verdict]}",
            f"**CI:** {ci}",
            "",
            "## Metrics",
            "",
            "| Metric | Value | Included | Status counts | Authority | Gate |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        lines += [self._metric_row(scorecard, metric) for metric in scorecard.metrics]
        # D3: per-metric evaluability -- the plan's pre-effect coverage (available/eligible) beside
        # the terminal measurement states, rendered from the typed PopulationSummary. An unknown
        # pre-effect count (a core-only or legacy scorecard) prints "?", never a misleading 0.
        if scorecard.populations:
            lines += _evaluability_lines(scorecard)
        # P3 (ADR 0047): failure clusters group failing/non-scored items by shared diagnostic cause.
        # Rendered from the typed Scorecard field only — no re-grouping here — and omitted entirely
        # when there are no clusters, so a pre-P3 report stays byte-identical.
        if scorecard.clusters:
            lines += ["", "## Failure clusters", ""]
            lines += [
                f"- **{c.metric}** · `{c.code}` ({c.severity.value}): {c.count} "
                f"case{'s' if c.count != 1 else ''} — {c.message}"
                for c in scorecard.clusters
            ]
        # D4: the run's honest, comparability-qualified change, rendered from the typed
        # ComparisonResult only — a numeric delta is shown only when the state is `comparable`; a
        # `not_comparable` run shows the changed fingerprint dimensions and no delta. Never a raw
        # previous-value subtraction. Omitted when no comparison was computed (no baseline).
        if scorecard.comparison is not None:
            lines += self._comparison_lines(scorecard.comparison)
        baseline = scorecard.baseline_state.value if scorecard.baseline_state is not None else "n/a"
        lines += ["", "## Baseline", "", baseline, "", "## Diagnostics", ""]
        if scorecard.diagnostics:
            lines += [
                f"- `{d.code}` ({d.severity.value}): {d.message}" for d in scorecard.diagnostics
            ]
        else:
            lines.append("- none")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _metric_row(scorecard: Scorecard, metric: AggregatedMetric) -> str:
        """One row of the Metrics table — value, coverage, and authority read from the Scorecard."""
        authority = scorecard.authority.get(metric.metric)
        level = authority.level.value if authority is not None else "n/a"
        reasons = ", ".join(authority.reasons) if authority and authority.reasons else "—"
        counts = ", ".join(f"{k}={v}" for k, v in sorted(metric.status_counts.items())) or "—"
        return (
            f"| {metric.metric} | {_value(metric.value)} | {metric.included_count} | "
            f"{counts} | {level} ({reasons}) | {gate_state(scorecard, metric.metric)} |"
        )

    def _comparison_lines(self, comparison: ComparisonResult) -> list[str]:
        """Render the typed comparison — a delta only when comparable; else why there is none."""
        lines = ["", "## Comparison", ""]
        base = f" vs baseline `{comparison.baseline_run_id}`" if comparison.baseline_run_id else ""
        lines.append(f"State: **{comparison.state.value}**{base}")
        if comparison.state is not BaselineState.COMPARABLE:
            if comparison.changed_dimensions:
                lines.append(
                    "Changed dimensions (why not comparable): "
                    + ", ".join(f"`{d}`" for d in comparison.changed_dimensions)
                )
            lines.append("No numeric delta can be claimed for a non-comparable run.")
            return lines
        lines += [
            "",
            "| Metric | Δ (direction-adjusted) | Outcome | Paired |",
            "| --- | --- | --- | --- |",
        ]
        deltas = comparison.comparison.deltas if comparison.comparison is not None else {}
        for name, delta in sorted(deltas.items()):
            adj = (
                "—"
                if delta.direction_adjusted_delta is None
                else f"{delta.direction_adjusted_delta:+.4g}"
            )
            lines.append(f"| {name} | {adj} | {delta.outcome.value} | {delta.n_paired} |")
        if comparison.skipped_metrics:
            lines.append("")
            lines.append(
                f"Skipped (no declared direction): {', '.join(comparison.skipped_metrics)}"
            )
        return lines


class TerminalScoreSink:
    """Render a Scorecard as a compact terminal summary."""

    def render(self, scorecard: Scorecard) -> str:
        payload = scorecard.verdict
        ci = "exit non-zero" if payload.ci_should_fail else "exit zero"
        lines = [
            f"verdict: {payload.verdict.value} ({_VERDICT_DESC[payload.verdict]}) [{ci}]",
        ]
        for metric in scorecard.metrics:
            authority = scorecard.authority.get(metric.metric)
            level = authority.level.value if authority is not None else "n/a"
            lines.append(
                f"  - {metric.metric}: value={_value(metric.value)} "
                f"included={metric.included_count} authority={level} "
                f"gate={gate_state(scorecard, metric.metric)}"
            )
        if scorecard.diagnostics:
            lines.append(f"  diagnostics: {len(scorecard.diagnostics)}")
        return "\n".join(lines)
