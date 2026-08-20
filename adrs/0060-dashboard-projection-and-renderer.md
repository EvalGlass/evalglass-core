# ADR 0060 — Diagnostic dashboard projection and default HTML renderer

**Status:** Accepted

## Context

The previous default `report.html` (ADR 0043) was self-contained and honest, but it inferred meaning
the typed artifacts never carried: it grouped metrics by the first segment of the metric name,
guessed each metric's tier from its authority reason text, and accepted a raw `previous_values`
mapping to draw a point-difference "delta" that looks like a regression even across non-comparable
runs. It also presented one report per surface without a deliberate first viewport, an attention
order, or evidence drill-down. The renderer, in other words, reconstructed display facts by heuristic
rather than reading them — the exact failure mode the no-false-confidence rule forbids.

The typed primary artifacts now carry every fact a decision surface needs — verdict, per-metric
authority (0057), population accounting (0058), the paired comparison (0059), estimates, diagnostic
clusters (0047), and complete judge evidence (0054) — but there was no single, versioned, score-
neutral view model a renderer could consume without re-deriving anything.

## Decision

Introduce a typed, versioned **dashboard projection** and make a **diagnostic-first HTML renderer**
the default, rendered entirely from that projection plus host-owned display metadata.

- **`evalglass.dashboard/1` projection** (`harness/dashboard.py`, `project_run`). A pure projection
  built from the typed `Scorecard`/`RunRecord` plus declared display metadata. It **copies** verdict,
  gate state, per-metric authority, population, interval, and comparison from the typed contracts and
  computes none of them: it imports no Verdict Engine and no authority resolver, and it performs no
  aggregate subtraction — a numeric delta is only ever the `direction_adjusted_delta` from the typed
  `Scorecard.comparison` (0059). A non-scored or invalid metric projects `value: null`, never a
  fabricated 0.
- **Host display metadata is score-neutral** (`metrics[].display`, `dashboard:` in the config). A
  label, workflow/group, tier, description, ordering, host links, and an attention rule — none of
  which grant authority or change a score, fingerprint, verdict, or CI exit. Absent metadata has
  deterministic neutral fallbacks: label = metric name, a single neutral workflow, and a **typed**
  tier fallback derived from the metric's declared lens/evaluator (a contract field), never from a
  name segment or an authority reason. An attention rule is explicitly labelled presentation policy.
- **A host-declared composite is the only licensed overall mean.** The dashboard shows coverage and
  never averages unrelated metrics; a `dashboard.composite` (named, weighted, versioned) is projected
  as declared when present, never computed by the renderer.
- **Default diagnostic renderer** (`harness/report_html.py` + packaged `harness/reporting/` template
  assets). One self-contained HTML file — inline CSS/JS, a `data:` favicon, the projection embedded
  as JSON with `<` escaped, a restrictive Content-Security-Policy, no external dependency — that works
  from `file://`. It presents the reference information hierarchy: verdict hero + authority strip,
  evaluability KPIs, workflow coverage bars (no implicit mean), a comparable-only forest plot,
  descriptive progression, a typed attention queue, and a searchable metric explorer with expandable
  call/judge evidence. The template is a single dashboard over **all** scores — no per-score report.
- **Template assets are packaged, not embedded.** The `.html`/`.css`/`.js` live under
  `harness/reporting/` and the installer vendors them verbatim alongside the managed packages, so a
  host's vendored renderer finds its template on disk and `report.html` renders after the plugin is
  removed.
- **`dashboard.json`** is written beside `scorecard.json`/`runrecord.json` as the projection artifact
  the HTML (and any external renderer) consumes; the Markdown report renders the same facts.
- **Legacy renderer, opt-in for one release.** The previous renderer moves to `report_html_legacy`
  and is selectable with `EVALGLASS_HTML_RENDERER=legacy`; it is scheduled for removal. The CLI no
  longer populates its `previous_values` delta (0059 deprecated it) — the raw same-run delta is gone.

## Consequences

- The renderer can no longer overclaim: it renders only typed facts and score-neutral metadata, and
  an informational run is never styled or described as a pass.
- The primary JSON artifacts (`scorecard.json`, `runrecord.json`, `report.md`) are byte-identical; a
  run additionally emits `dashboard.json` and `report.html` from the projection. Adding
  `metrics[].display` or `dashboard:` to a config changes only the projection/renderings, never the
  scoring, authority, fingerprints, or verdict.
- A new versioned public contract (`evalglass.dashboard/1`) and vendored template assets are added;
  older projection consumers ignore unknown additive fields.
- The heuristic name/reason grouping and the raw `previous_values` delta are removed from the default
  path; the legacy renderer preserves the old shape for one compatibility release only.
