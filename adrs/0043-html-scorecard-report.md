# ADR 0043 — HTML Scorecard report (dashboard + deltas)

- **Status:** accepted
- **Date:** 2026-07-20
- **Relates to:** ADR 0028 (authority is ledger-only), EG-M1-5 (Markdown/terminal sinks)

## Context

The only rendered report was Markdown — a table. Reviewers wanted a results-first, scannable
view: the verdict at a glance, each metric's **confidence interval** (not just the point), the
typed authority explanation, and the **movement vs the previous run**. A report must never add
authority the Scorecard does not hold (ADR 0028; CLAUDE.md §11).

## Decision

Add `harness/report_html.py::HtmlScoreSink` — a pure, stdlib-only `ScoreSink` that renders one
**self-contained** HTML dashboard from the typed Scorecard, and wire the CLI to write `report.html`
alongside `report.md`.

| Concern | Choice |
|---|---|
| Rendering | Pure `render(scorecard) -> str`; the CLI does the I/O (like the other sinks). Self-contained (inline CSS + inline SVG bands, no external assets) — CSP-safe, works offline. |
| Content | Verdict hero (hue per verdict), KPI tiles, per-workflow metric rows with an **interval band** (the Wilson/Student-t `[lower, upper]` shaded with the point marked), tier/authority chips, and a "what this run does not claim" panel. |
| Authority | Every gate state comes from `gate_state` (shared with the Markdown/CI sinks); the honesty panel is derived from the typed authority reasons (`judge_uncalibrated`, non-evaluable, baseline state). The page adds no verdict and no authority. |
| Delta | Optional `previous_values` (metric → prior point value) yields per-metric delta chips + a summary. The CLI reads the run dir's existing `scorecard.json` (the same-id previous run) before persist overwrites it. Best-effort: a missing/garbled prior run is simply "no delta" and never affects the verdict/exit. |
| Theme | Dark-default with a light mode; `prefers-color-scheme` + a `data-theme` override. Validated dataviz palette (status hues reserved, never reused as categorical). |

## Consequences

- A reviewer sees the verdict, the honest uncertainty (interval bands), and what moved since the
  last run, without reading a table — while the report still says exactly what the Scorecard says.
- The delta is convenience only (same-id previous run); a rigorous regression claim still goes
  through the baseline/comparability path, not the report.
- `report.html` is derived output; `scorecard.json`/`runrecord.json` remain the source of truth.

## Alternatives considered

- **Charting library / external assets.** Rejected — a report must be self-contained and offline
  (inline SVG bars are enough for the interval band).
- **Reconstruct a prior Scorecard for the delta.** Rejected — the report needs only prior point
  values; a `metric → value` map keeps the sink decoupled from full-Scorecard deserialization.
- **Fold the delta into the baseline comparison.** Rejected for the header delta (a lightweight
  "since last run" affordance); the authoritative regression claim stays in the baseline path.
