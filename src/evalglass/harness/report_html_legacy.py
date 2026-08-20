"""Legacy HTML Scorecard renderer — kept opt-in for one compatibility release (ADR 0043/0060).

The diagnostic-first dashboard (``report_html.py`` + ``reporting/``) is the default renderer as of
Epic E. This module preserves the previous self-contained per-metric HTML for one release so a host
that depends on its exact shape can opt in via ``EVALGLASS_HTML_RENDERER=legacy``; it will be removed
in a following release. It groups by the first metric-name segment and infers tier from authority
reasons — the name/reason heuristics the new renderer deliberately removes — and its raw
``previous_values`` delta is no longer populated by the CLI (D4 supplies typed comparison instead).

A *rendering* of the typed ``Scorecard``: the verdict, per-metric aggregates with their
**confidence interval** (the epistemic honesty made visual — the Wilson/Student-t band, not just
the point), the typed authority explanation, and an optional **delta vs a previous run**. Like the
Markdown/terminal sinks it never recomputes the verdict or authority (build contract §9; CLAUDE.md
§11): the headline verdict text and every gate state come straight from ``scorecard.verdict``.

Pure + stdlib-only: ``render`` returns one self-contained HTML string (inline CSS, inline SVG
bars, no external assets, no network) — the CLI writes it to ``report.html``. Theme-aware
(dark-default with a light mode). ``previous`` (a prior run's Scorecard) enables per-metric deltas;
``meta`` carries run_id / generated-at / source labels the Scorecard itself does not hold.
"""

# ruff: noqa: E501 — this module embeds a CSS/HTML template where hard-wrapping hurts readability.
from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass

from evalglass.core import Scorecard, Verdict
from evalglass.harness.report import gate_state

_VERDICT_DESC: dict[Verdict, str] = {
    Verdict.INFORMATIONAL: "no active gate — this run does not assert pass/fail quality",
    Verdict.PASS: "every active gate passed its approved threshold",
    Verdict.FAIL: "an active gate is validly measured below its approved threshold",
    Verdict.BLOCKED: "an active gate cannot make an honest quality claim",
}
# Status hue per verdict (validated palette): informational=neutral blue, pass=good, fail=critical,
# blocked=warning. Never implies more than the verdict word.
_VERDICT_HUE: dict[Verdict, str] = {
    Verdict.INFORMATIONAL: "#3987e5",
    Verdict.PASS: "#0ca30c",
    Verdict.FAIL: "#d03b3b",
    Verdict.BLOCKED: "#fab219",
}


@dataclass(frozen=True)
class ReportMeta:
    """Run labels the Scorecard does not carry (rendered as-is, never authority)."""

    run_id: str = ""
    generated_at: str = ""
    source: str = ""  # e.g. "langfuse-trace lane" / "local traces" / "no platform"
    app: str = ""


def _esc(text: object) -> str:
    return html.escape(str(text))


def _workflow(metric_name: str) -> str:
    return metric_name.split(".", 1)[0] if "." in metric_name else metric_name


def _short(metric_name: str) -> str:
    return metric_name.split(".", 1)[1] if "." in metric_name else metric_name


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3g}"


class HtmlScoreSink:
    """Render a Scorecard as a self-contained HTML dashboard."""

    def __init__(
        self,
        *,
        previous_values: Mapping[str, float | None] | None = None,
        meta: ReportMeta | None = None,
    ) -> None:
        # Just the prior run's per-metric point values (metric -> value) — enough for the delta,
        # and decoupled from reconstructing a whole prior Scorecard.
        self._previous = dict(previous_values or {})
        self._meta = meta or ReportMeta()

    # -- data helpers (read-only over the typed Scorecard) --------------------

    def _estimates(self, scorecard: Scorecard) -> dict[str, object]:
        return {e.metric: e for e in getattr(scorecard, "estimates", []) or []}

    def _prev_values(self) -> dict[str, float | None]:
        return self._previous

    def _tier(self, scorecard: Scorecard, metric_name: str) -> str:
        authority = scorecard.authority.get(metric_name)
        reasons = set(authority.reasons) if authority and authority.reasons else set()
        if any("judge" in r for r in reasons):
            return "judge"
        summary = next((m for m in scorecard.metrics if m.metric == metric_name), None)
        if summary is not None and summary.included_count == 0:
            return "reference"  # scored nothing here — needs gold / not applicable
        return "runtime"

    # -- rendering ------------------------------------------------------------

    def render(self, scorecard: Scorecard) -> str:
        payload = scorecard.verdict
        verdict = payload.verdict
        ests = self._estimates(scorecard)
        prev = self._prev_values()
        parts = [
            _STYLE,
            '<div class="eg">',
            self._hero(scorecard, verdict),
            self._kpis(scorecard),
            self._delta_summary(scorecard, prev),
        ]
        for wf in self._ordered_workflows(scorecard):
            parts.append(self._workflow_section(scorecard, wf, ests, prev))
        parts.append(self._honesty(scorecard))
        parts.append(self._footer())
        parts.append("</div>")
        return "\n".join(parts)

    def _ordered_workflows(self, scorecard: Scorecard) -> list[str]:
        seen: list[str] = []
        for m in scorecard.metrics:
            wf = _workflow(m.metric)
            if wf not in seen:
                seen.append(wf)
        return seen

    def _hero(self, scorecard: Scorecard, verdict: Verdict) -> str:
        payload = scorecard.verdict
        hue = _VERDICT_HUE.get(verdict, "#3987e5")
        ci = "exit non-zero" if payload.ci_should_fail else "exit zero"
        m = self._meta
        bits = [b for b in (m.app, m.source, m.run_id, m.generated_at) if b]
        sub = " · ".join(_esc(b) for b in bits)
        return (
            f'<header class="hero" style="--vh:{hue}">'
            f'<div class="vbadge">{_esc(verdict.value)}</div>'
            f'<div class="hmain"><div class="vdesc">{_esc(_VERDICT_DESC[verdict])}</div>'
            f'<div class="hsub">{sub}{" · " if sub else ""}CI {ci}</div></div>'
            f"</header>"
        )

    def _kpis(self, scorecard: Scorecard) -> str:
        metrics = scorecard.metrics
        scored = sum(1 for m in metrics if (m.value is not None and m.included_count > 0))
        non_eval = sum(1 for m in metrics if m.included_count == 0)
        judge = sum(1 for m in metrics if self._tier(scorecard, m.metric) == "judge")
        gates = (
            len(scorecard.verdict.passing_gates)
            + len(scorecard.verdict.failing_gates)
            + len(scorecard.verdict.blocked_gates)
        )
        examples = max((m.included_count for m in metrics), default=0)
        tiles = [
            ("metrics", len(metrics), ""),
            ("scored", scored, "good"),
            ("non-evaluable", non_eval, "muted"),
            ("judge (uncal.)", judge, "warn"),
            ("active gates", gates, "muted" if gates == 0 else "warn"),
            ("examples", examples, ""),
        ]
        cells = "".join(
            f'<div class="kpi {cls}"><div class="kn">{_esc(n)}</div>'
            f'<div class="kl">{_esc(label)}</div></div>'
            for label, n, cls in tiles
        )
        return f'<section class="kpis">{cells}</section>'

    def _delta_summary(self, scorecard: Scorecard, prev: Mapping[str, float | None]) -> str:
        if not prev:
            return ""
        moved = []
        for m in scorecard.metrics:
            pv = prev.get(m.metric)
            if pv is None or m.value is None:
                continue
            d = m.value - pv
            if abs(d) >= 0.005:
                moved.append((m.metric, d))
        if not moved:
            return (
                '<section class="delta-note">Compared to the previous run: '
                "no metric moved by more than 0.005.</section>"
            )
        moved.sort(key=lambda x: -abs(x[1]))
        chips = "".join(
            f'<span class="dchip {"up" if d > 0 else "down"}">'
            f"{_esc(_short(name))} {'▲' if d > 0 else '▼'}{abs(d):.2g}</span>"
            for name, d in moved[:8]
        )
        return (
            '<section class="delta-note"><b>Δ vs previous run</b> '
            f'<span class="dsub">(raw point movement; a move inside the interval is noise)</span>'
            f'<div class="dchips">{chips}</div></section>'
        )

    def _workflow_section(
        self,
        scorecard: Scorecard,
        workflow: str,
        ests: Mapping[str, object],
        prev: Mapping[str, float | None],
    ) -> str:
        rows = [
            self._metric_row(scorecard, m, ests.get(m.metric), prev.get(m.metric))
            for m in scorecard.metrics
            if _workflow(m.metric) == workflow
        ]
        return (
            f'<section class="wf"><h2>{_esc(workflow)}</h2>'
            f'<div class="rows">{"".join(rows)}</div></section>'
        )

    def _metric_row(
        self,
        scorecard: Scorecard,
        summary: object,
        estimate: object | None,
        prev_value: float | None,
    ) -> str:
        name = summary.metric  # type: ignore[attr-defined]
        value = summary.value  # type: ignore[attr-defined]
        included = summary.included_count  # type: ignore[attr-defined]
        tier = self._tier(scorecard, name)
        authority = scorecard.authority.get(name)
        reasons = list(authority.reasons) if authority and authority.reasons else []
        chips = "".join(f'<span class="chip">{_esc(r)}</span>' for r in reasons)
        gate = gate_state(scorecard, name)
        band = self._interval_band(value, estimate)
        delta = ""
        if prev_value is not None and value is not None:
            d = value - prev_value
            if abs(d) >= 0.005:
                cls = "up" if d > 0 else "down"
                delta = f'<span class="delta {cls}">{"▲" if d > 0 else "▼"}{abs(d):.2g}</span>'
        n_txt = ""
        if estimate is not None and getattr(estimate, "n_effective", None):
            n_txt = f'<span class="nof">n={estimate.n_effective}</span>'  # type: ignore[attr-defined]
        return (
            f'<div class="row t-{tier}">'
            f'<div class="mname"><span class="tier {tier}">{tier}</span>'
            f'<span class="mn">{_esc(_short(name))}</span></div>'
            f'<div class="mval">{_fmt(value)}{delta}</div>'
            f'<div class="mband">{band}{n_txt}</div>'
            f'<div class="mmeta"><span class="incl">{included}&#215;</span>'
            f'<span class="gate g-{gate}">{_esc(gate)}</span>{chips}</div>'
            f"</div>"
            f"{self._cluster_rows(scorecard, name)}"
        )

    def _cluster_rows(self, scorecard: Scorecard, name: str) -> str:
        """Failure-cluster sub-rows for one metric — typed Scorecard field only (P3; ADR 0047).

        Reads ``scorecard.clusters`` for this metric and renders a sub-row per failure mode
        (``<code> · N cases``). No re-grouping and no authority: a cluster is explanatory
        structure, and a non-scored item is shown by count, never as a ``0.0`` value.
        """
        rows = [
            f'<div class="cluster sev-{c.severity.value}">'
            f'<span class="ccode">{_esc(c.code)}</span>'
            f'<span class="ccount">{c.count} case{"s" if c.count != 1 else ""}</span>'
            f'<span class="cmsg">{_esc(c.message)}</span></div>'
            for c in scorecard.clusters
            if c.metric == name
        ]
        return "".join(rows)

    def _interval_band(self, value: float | None, estimate: object | None) -> str:
        """A [0,1] track with the CI band shaded + the point marked (honest uncertainty)."""
        w, h = 168, 16
        track = f'<rect x="0" y="{h // 2 - 2}" width="{w}" height="4" rx="2" class="trk"/>'
        if value is None:
            return (
                f'<svg class="band" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{track}'
                f'<text x="{w // 2}" y="{h - 3}" class="na">not evaluated</text></svg>'
            )
        lo = hi = value
        method = ""
        if estimate is not None and getattr(estimate, "interval", None) is not None:
            iv = estimate.interval  # type: ignore[attr-defined]
            lo, hi = float(iv.lower), float(iv.upper)
            method = str(getattr(iv, "method", ""))

        def x(v: float) -> float:
            return max(0.0, min(1.0, v)) * w

        band = (
            f'<rect x="{x(lo):.1f}" y="{h // 2 - 4}" width="{max(2.0, x(hi) - x(lo)):.1f}" '
            f'height="8" rx="3" class="ci"/>'
        )
        pt = f'<circle cx="{x(value):.1f}" cy="{h // 2}" r="3.5" class="pt"/>'
        title = f"point {value:.3g}; {method} [{lo:.2g}, {hi:.2g}]" if method else f"{value:.3g}"
        return (
            f'<svg class="band" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f"<title>{_esc(title)}</title>{track}{band}{pt}</svg>"
        )

    def _honesty(self, scorecard: Scorecard) -> str:
        notes = ["This run is <b>informational</b> — a non-failing result is not proof of quality."]
        if any(self._tier(scorecard, m.metric) == "judge" for m in scorecard.metrics):
            notes.append(
                "Judge metrics are <b>uncalibrated</b> → they cannot gate until a host computes "
                "an agreement study against SME labels."
            )
        if any(m.included_count == 0 for m in scorecard.metrics):
            notes.append(
                "Metrics that scored nothing are <b>non-evaluable</b> here (e.g. reference metrics "
                "await host gold) — honest absence, never a fabricated 0."
            )
        baseline = scorecard.baseline_state.value if scorecard.baseline_state is not None else "n/a"
        notes.append(f"Baseline comparability: <b>{_esc(baseline)}</b>.")
        items = "".join(f"<li>{n}</li>" for n in notes)
        return (
            '<section class="honesty"><h2>What this run does not claim</h2>'
            f"<ul>{items}</ul></section>"
        )

    def _footer(self) -> str:
        return (
            '<footer class="foot">Rendered from the typed Scorecard by EvalGlass. '
            "The verdict comes from the Verdict Engine; this page adds no authority.</footer>"
        )


_STYLE = """<style>
.eg{--bg:#0d0d0d;--surf:#1a1a19;--surf2:#222220;--ink:#fff;--ink2:#c3c2b7;--mut:#898781;
--line:#2c2c2a;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--up:#0ca30c;--down:#e66767;
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);
background:var(--bg);max-width:1080px;margin:0 auto;padding:20px;box-sizing:border-box}
.eg *{box-sizing:border-box}
@media (prefers-color-scheme:light){.eg{--bg:#f9f9f7;--surf:#fcfcfb;--surf2:#f2f1ee;--ink:#0b0b0b;
--ink2:#52514e;--mut:#898781;--line:#e1e0d9;--down:#d03b3b}}
:root[data-theme=dark] .eg{--bg:#0d0d0d;--surf:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--line:#2c2c2a}
:root[data-theme=light] .eg{--bg:#f9f9f7;--surf:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e1e0d9}
.hero{display:flex;gap:16px;align-items:center;background:var(--surf);border:1px solid var(--line);
border-left:5px solid var(--vh);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.vbadge{font-weight:700;font-size:15px;letter-spacing:.04em;text-transform:uppercase;color:#fff;
background:var(--vh);padding:6px 12px;border-radius:8px;white-space:nowrap}
.hmain{min-width:0}.vdesc{font-size:15px;color:var(--ink)}
.hsub{color:var(--mut);font-size:12.5px;margin-top:2px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kn{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.kl{color:var(--mut);font-size:12px;margin-top:2px}
.kpi.good .kn{color:var(--good)}.kpi.warn .kn{color:var(--warn)}.kpi.muted .kn{color:var(--mut)}
.delta-note{background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:12px 14px;
margin-bottom:16px;font-size:13px}.dsub{color:var(--mut);font-weight:400}
.dchips{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px}
.dchip{font-size:12px;padding:3px 8px;border-radius:6px;font-variant-numeric:tabular-nums}
.dchip.up{background:rgba(12,163,12,.14);color:var(--up)}
.dchip.down{background:rgba(230,103,103,.16);color:var(--down)}
.wf{background:var(--surf);border:1px solid var(--line);border-radius:12px;padding:6px 16px 14px;
margin-bottom:14px}.wf h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;
color:var(--ink2);margin:14px 2px 8px}
.row{display:grid;grid-template-columns:minmax(200px,1.4fr) 88px 210px minmax(160px,1fr);
gap:10px;align-items:center;padding:8px 6px;border-top:1px solid var(--line)}
.mname{display:flex;align-items:center;gap:8px;min-width:0}
.mn{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tier{font-size:10px;text-transform:uppercase;letter-spacing:.03em;padding:2px 6px;border-radius:5px;
font-weight:600;flex:none}
.tier.runtime{background:rgba(57,135,229,.16);color:#6da7ec}
.tier.judge{background:rgba(250,178,25,.16);color:var(--warn)}
.tier.reference{background:rgba(137,135,129,.18);color:var(--mut)}
.mval{font-size:17px;font-weight:650;font-variant-numeric:tabular-nums;text-align:right}
.delta{font-size:11px;font-weight:600;margin-left:6px;vertical-align:middle}
.delta.up{color:var(--up)}.delta.down{color:var(--down)}
.band .trk{fill:var(--line)}.band .ci{fill:rgba(57,135,229,.35)}.band .pt{fill:#3987e5}
.band .na{fill:var(--mut);font-size:10px;text-anchor:middle}
.nof{color:var(--mut);font-size:11px;margin-left:8px;font-variant-numeric:tabular-nums}
.mmeta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:flex-end}
.incl{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
.gate{font-size:10.5px;padding:2px 7px;border-radius:5px;text-transform:uppercase;letter-spacing:.03em}
.g-informational{background:rgba(137,135,129,.18);color:var(--mut)}
.g-pass{background:rgba(12,163,12,.16);color:var(--good)}
.g-fail{background:rgba(208,59,59,.18);color:var(--crit)}
.g-blocked{background:rgba(250,178,25,.16);color:var(--warn)}
.chip{font-size:10.5px;color:var(--mut);background:var(--surf2);border:1px solid var(--line);
padding:2px 6px;border-radius:5px}
.cluster{display:flex;gap:8px;align-items:baseline;font-size:11.5px;color:var(--mut);
padding:3px 6px 3px 16px;border-left:2px solid var(--line);margin:1px 0 1px 8px}
.cluster.sev-error{border-left-color:var(--bad,#c0563b)}
.cluster.sev-warning{border-left-color:var(--warn,#b58a2e)}
.ccode{font-family:ui-monospace,monospace;color:var(--ink2)}
.ccount{font-variant-numeric:tabular-nums}.cmsg{color:var(--mut);overflow:hidden;text-overflow:ellipsis}
.honesty{background:var(--surf);border:1px solid var(--line);border-radius:12px;padding:6px 18px 14px;
margin-bottom:14px}.honesty h2{font-size:14px;color:var(--ink2);text-transform:uppercase;
letter-spacing:.05em}.honesty ul{margin:0;padding-left:18px}.honesty li{margin:6px 0;color:var(--ink2)}
.honesty b{color:var(--ink)}
.foot{color:var(--mut);font-size:12px;text-align:center;padding:8px 0}
@media (max-width:720px){.row{grid-template-columns:1fr 70px;grid-auto-flow:row}
.mband,.mmeta{grid-column:1/-1;justify-content:flex-start}}
</style>"""
