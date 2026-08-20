"""CI annotation sink — GitHub Actions workflow commands from a Scorecard (EG-M2-3).

A :class:`~evalglass.harness.ports.ScoreSink` that renders immutable Scorecard data as GitHub
workflow-command annotations (``::error``/``::warning``/``::notice``). It never recomputes the
verdict or authority: the headline verdict and every per-metric gate state come straight from
the :class:`~evalglass.core.VerdictPayload`, and every verdict word is sourced from the
:class:`~evalglass.core.Verdict` enum (no string literals — the M1 scan-gate lesson). A failing
or blocked gate becomes an ``::error``; an informational or passing run emits none. The literal
approved threshold is deliberately not cited — it is not a Scorecard field, and this sink renders
only what the Scorecard holds (build contract §9). Stdlib-only, effect-free.
"""

from __future__ import annotations

from evalglass.core import Scorecard, Verdict
from evalglass.harness.report import gate_state

# GitHub workflow-command level per gate state. Keyed by the Verdict enum's values, never by
# verdict string literals, so the mapping stays in lockstep with the engine's vocabulary.
_LEVEL: dict[str, str] = {
    Verdict.FAIL.value: "error",
    Verdict.BLOCKED.value: "error",
    Verdict.PASS.value: "notice",
    Verdict.INFORMATIONAL.value: "notice",
}


def _value(value: float | None) -> str:
    return "none" if value is None else f"{value:.4g}"


def _esc_data(text: str) -> str:
    """Escape a workflow-command *message* per GitHub's rules (order matters: ``%`` first)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(text: str) -> str:
    """Escape a workflow-command *property value* (a title): also ``:`` and ``,``."""
    return _esc_data(text).replace(":", "%3A").replace(",", "%2C")


class CiAnnotationSink:
    """Render a Scorecard as GitHub Actions workflow-command annotations.

    Host-derived strings (metric names, authority reasons, diagnostic codes/messages) are
    escaped per GitHub's workflow-command rules before interpolation, so a newline or ``::``
    in any field cannot split the output into a spurious extra command.
    """

    def render(self, scorecard: Scorecard) -> str:
        payload = scorecard.verdict
        ci = "exit-nonzero" if payload.ci_should_fail else "exit-zero"
        # Headline: exactly the product verdict, never another verdict word (no overclaim).
        lines = [f"::notice title=EvalGlass::verdict={payload.verdict.value} ci={ci}"]
        for metric in scorecard.metrics:
            state = gate_state(scorecard, metric.metric)
            authority = scorecard.authority.get(metric.metric)
            authority_reasons = (
                ", ".join(authority.reasons) if authority and authority.reasons else "none"
            )
            verdict_reasons = ", ".join(payload.reasons.get(metric.metric, [])) or "none"
            lines.append(
                f"::{_LEVEL[state]} title={_esc_prop(metric.metric)}::"
                f"gate={state} value={_value(metric.value)} "
                f"reasons={_esc_data(verdict_reasons)} authority={_esc_data(authority_reasons)}"
            )
        # Diagnostics are explanatory context, never a verdict — emitted as warnings.
        lines.extend(
            f"::warning title={_esc_prop(d.code)}::{_esc_data(d.message)}"
            for d in scorecard.diagnostics
        )
        return "\n".join(lines) + "\n"
