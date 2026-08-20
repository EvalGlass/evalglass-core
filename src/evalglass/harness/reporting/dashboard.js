(() => {
  "use strict";

  const payloadNode = document.getElementById("dashboard-data");
  const data = JSON.parse(payloadNode.textContent);
  const byId = (id) => document.getElementById(id);
  const finite = (value) => Number.isFinite(value);
  const clamp = (value, low = 0, high = 1) =>
    Math.max(low, Math.min(high, Number(value) || 0));
  const clean = (value) => String(value ?? "").replaceAll("**", "");
  const escapeHtml = (value) =>
    clean(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  const slug = (value) =>
    String(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  const titleCase = (value) =>
    String(value ?? "")
      .replaceAll("_", " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  const compactId = (value) => {
    const text = String(value ?? "");
    return text.length <= 30 ? text : `${text.slice(0, 16)}…${text.slice(-9)}`;
  };
  const percentage = (value) => (finite(value) ? `${Math.round(value * 100)}%` : "—");
  const scored = (metric) =>
    metric.status === "scored" && metric.validity === "valid" && finite(metric.value);
  const metricValue = (metric) => (scored(metric) ? percentage(metric.value) : "—");
  const comparisonIsValid = (metric) =>
    data.comparison?.state === "comparable" &&
    metric.comparison?.state === "comparable" &&
    finite(metric.comparison?.direction_adjusted_delta);
  const deltaText = (metric) => {
    if (!comparisonIsValid(metric)) return "n/c";
    const value = metric.comparison.direction_adjusted_delta;
    if (Math.abs(value) < 0.0005) return "0.0 pp";
    return `${value > 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(1)} pp`;
  };
  const diagnosticText = (metric) => {
    if (metric.gate?.state === "blocked") return "An active gate could not make a quality claim.";
    if (metric.gate?.state === "fail") return "An active gate validly failed its decision rule.";
    if (metric.status === "error") return metric.diagnostics?.[0]?.message || "Measurement error.";
    if (!scored(metric)) {
      return metric.diagnostics?.[0]?.message || `Metric is ${metric.status.replaceAll("_", " ")}.`;
    }
    if (metric.comparison?.outcome === "regression") {
      return `Comparable regression of ${deltaText(metric).replace("−", "-")}.`;
    }
    return (
      metric.diagnostics?.[0]?.message ||
      metric.authority?.reasons?.[0]?.replaceAll("_", " ") ||
      "Review the metric evidence."
    );
  };
  const needsAttention = (metric) =>
    !scored(metric) ||
    metric.gate?.state === "blocked" ||
    metric.gate?.state === "fail" ||
    metric.comparison?.outcome === "regression" ||
    Boolean(metric.diagnostics?.length);

  function renderHero() {
    const verdict = data.verdict || {};
    const state = verdict.state || "informational";
    byId("verdict-title").innerHTML =
      `${escapeHtml(titleCase(state))}<span class="verdict-word">evidence</span>`;
    const pill = byId("verdict-pill");
    const ciText = verdict.ci_should_fail ? "exits non-zero" : "exits zero";
    pill.textContent =
      state === "informational" ? "No quality pass asserted" : `CI ${ciText}`;
    pill.className = `verdict-pill ${escapeHtml(state)}`;
    byId("verdict-description").textContent =
      verdict.description || "No verdict description was provided.";
    const run = data.run || {};
    const timestamp = run.generated_at ? new Date(run.generated_at).toLocaleString() : "Unknown time";
    byId("run-meta").innerHTML = [
      run.application,
      run.id,
      timestamp,
      run.source_label,
    ]
      .filter(Boolean)
      .map((item) => `<span>${escapeHtml(item)}</span>`)
      .join("");

    const facts = [
      ["Dataset", data.authority?.dataset || "unknown"],
      ["Thresholds", data.authority?.thresholds || "unknown"],
      ["Judges", data.authority?.judges || "not configured"],
      ["Comparison", data.comparison?.state || "comparison not requested"],
    ];
    byId("authority-strip").innerHTML = facts
      .map(
        ([label, value]) => `
          <div class="authority-item">
            <dt>${escapeHtml(label)}</dt>
            <dd title="${escapeHtml(value)}">${escapeHtml(String(value).replaceAll("_", " "))}</dd>
          </div>`,
      )
      .join("");
  }

  function renderKpis() {
    const summary = data.summary || {};
    const attention = data.metrics.filter(needsAttention).length;
    const metricsTotal = Number(summary.metrics_total) || data.metrics.length;
    const metricsScored =
      Number(summary.metrics_scored) || data.metrics.filter((metric) => scored(metric)).length;
    const kpis = [
      {
        value: `${metricsScored}/${metricsTotal}`,
        label: "Evaluable metrics",
        note: `${percentage(metricsTotal ? metricsScored / metricsTotal : 0)} measured`,
      },
      {
        value: summary.examples ?? "—",
        label: "Evaluation examples",
        note: `${summary.call_scores ?? 0} call-level scores`,
      },
      {
        value: attention,
        label: "Needs attention",
        note: `${summary.diagnostics ?? 0} diagnostic clusters`,
      },
      {
        value: data.authority?.active_gates ?? 0,
        label: "Active gates",
        note: data.verdict?.state === "informational" ? "No quality gate" : "Verdict-controlled",
      },
    ];
    byId("kpis").innerHTML = kpis
      .map(
        (item) => `
          <article class="kpi">
            <strong class="kpi-value">${escapeHtml(item.value)}</strong>
            <span class="kpi-label">${escapeHtml(item.label)}</span>
            <span class="kpi-note">${escapeHtml(item.note)}</span>
          </article>`,
      )
      .join("");
  }

  function workflowStats() {
    const groups = new Map();
    for (const metric of data.metrics) {
      const workflow = metric.workflow || "Other";
      if (!groups.has(workflow)) groups.set(workflow, []);
      groups.get(workflow).push(metric);
    }
    return [...groups.entries()]
      .map(([name, metrics]) => ({
        name,
        total: metrics.length,
        measured: metrics.filter(scored).length,
        attention: metrics.filter(needsAttention).length,
        gates: metrics.filter((metric) => ["pass", "fail", "blocked"].includes(metric.gate?.state))
          .length,
      }))
      .sort((left, right) => right.attention - left.attention || left.name.localeCompare(right.name));
  }

  function renderWorkflows() {
    byId("workflow-chart").innerHTML = workflowStats()
      .map((item) => {
        const coverage = item.total ? item.measured / item.total : 0;
        const attentionLabel = item.attention
          ? `<span class="attention-count" title="${item.attention} metric(s) need attention">${item.attention}</span>`
          : "";
        return `
          <div class="workflow-row">
            <div class="workflow-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
            <div class="workflow-track" role="img" aria-label="${escapeHtml(item.name)}: ${item.measured} of ${item.total} metrics evaluable">
              <div class="workflow-fill" style="width:${coverage * 100}%"></div>
            </div>
            <div class="workflow-meta">
              <span>${item.measured}/${item.total} measured</span>
              ${attentionLabel}
            </div>
          </div>`;
      })
      .join("");
  }

  function attentionRank(metric) {
    if (metric.gate?.state === "blocked") return 0;
    if (metric.gate?.state === "fail") return 1;
    if (metric.status === "error") return 2;
    if (!scored(metric)) return 3;
    if (metric.comparison?.outcome === "regression") return 4;
    if (metric.diagnostics?.length) return 5;
    return 6;
  }

  function renderAttention() {
    const items = data.metrics
      .filter(needsAttention)
      .sort(
        (left, right) =>
          attentionRank(left) - attentionRank(right) ||
          (left.value ?? Number.POSITIVE_INFINITY) -
            (right.value ?? Number.POSITIVE_INFINITY),
      )
      .slice(0, 7);
    byId("attention-subtitle").textContent = items.length
      ? `${data.metrics.filter(needsAttention).length} metrics require review.`
      : "No typed attention condition is present.";
    byId("attention-list").innerHTML = items.length
      ? items
          .map(
            (metric) => `
              <button class="attention-item" type="button" data-open="${escapeHtml(metric.name)}">
                <span>
                  <span class="attention-name">${escapeHtml(metric.label || metric.name)}</span>
                  <span class="attention-reason">${escapeHtml(diagnosticText(metric))}</span>
                </span>
                <span class="attention-value">${escapeHtml(metricValue(metric))}</span>
              </button>`,
          )
          .join("")
      : '<div class="empty-state">No metric currently meets the dashboard attention rules.</div>';
  }

  function renderComparison() {
    const comparison = data.comparison || {};
    const target = byId("comparison-chart");
    const subtitle = byId("comparison-subtitle");
    const legend = byId("comparison-legend");
    if (comparison.state !== "comparable") {
      subtitle.textContent = String(comparison.state || "comparison_not_requested").replaceAll(
        "_",
        " ",
      );
      const changed = comparison.changed_dimensions || [];
      target.innerHTML = `<div class="comparison-empty">${
        changed.length
          ? `No delta: score-determining dimensions changed (${escapeHtml(changed.join(", "))}).`
          : "No paired comparable baseline is available, so this report makes no regression claim."
      }</div>`;
      legend.innerHTML = "";
      return;
    }
    const metrics = data.metrics
      .filter(comparisonIsValid)
      .sort((left, right) => {
        const order = { regression: 0, improvement: 1, within_noise: 2 };
        return (
          (order[left.comparison.outcome] ?? 3) - (order[right.comparison.outcome] ?? 3) ||
          Math.abs(right.comparison.direction_adjusted_delta) -
            Math.abs(left.comparison.direction_adjusted_delta)
        );
      })
      .slice(0, 10);
    subtitle.textContent = `Direction-adjusted paired deltas vs ${comparison.baseline_run_id || "baseline"} · ${comparison.shared_examples ?? "—"} shared examples`;
    legend.innerHTML = `
      <span><i class="legend-swatch regression"></i>Regression</span>
      <span><i class="legend-swatch improvement"></i>Improvement</span>
      <span><i class="legend-swatch noise"></i>Within noise</span>`;
    if (!metrics.length) {
      target.innerHTML =
        '<div class="comparison-empty">The run is comparable, but no metric has a numeric paired delta.</div>';
      return;
    }
    const values = metrics.flatMap((metric) => {
      const interval = metric.comparison.interval;
      return [
        metric.comparison.direction_adjusted_delta,
        interval?.lower,
        interval?.upper,
      ].filter(finite);
    });
    const domain = Math.max(0.05, ...values.map((value) => Math.abs(value)));
    const position = (value) => clamp(50 + (value / (domain * 2)) * 100, 0, 100);
    target.innerHTML = `
      <div class="delta-axis" aria-hidden="true">
        <span></span>
        <span class="delta-scale"><span>−${(domain * 100).toFixed(0)} pp</span><span>0</span><span>+${(domain * 100).toFixed(0)} pp</span></span>
        <span></span>
      </div>
      ${metrics
        .map((metric) => {
          const value = metric.comparison.direction_adjusted_delta;
          const interval = metric.comparison.interval || { lower: value, upper: value };
          const left = position(interval.lower);
          const right = position(interval.upper);
          const outcome = metric.comparison.outcome || "within_noise";
          return `
            <div class="delta-row ${escapeHtml(outcome)}">
              <div class="delta-label" title="${escapeHtml(metric.name)}">${escapeHtml(metric.label || metric.name)}</div>
              <div class="delta-plot" role="img" aria-label="${escapeHtml(metric.label || metric.name)} ${escapeHtml(outcome)} ${escapeHtml(deltaText(metric))}; interval ${escapeHtml((interval.lower * 100).toFixed(1))} to ${escapeHtml((interval.upper * 100).toFixed(1))} percentage points">
                <span class="delta-track"></span>
                <span class="delta-zero"></span>
                <span class="delta-interval" style="left:${left}%;width:${Math.max(1, right - left)}%"></span>
                <span class="delta-point" style="left:${position(value)}%"></span>
              </div>
              <div class="delta-value">
                <strong>${escapeHtml(deltaText(metric))}</strong>
                <span>${escapeHtml(outcome.replaceAll("_", " "))}</span>
              </div>
            </div>`;
        })
        .join("")}`;
  }

  function renderProgression() {
    const history = data.history || [];
    const target = byId("progression-chart");
    if (!history.length) {
      target.innerHTML = '<div class="empty-state">Descriptive history begins with the next run.</div>';
      return;
    }
    const width = 760;
    const height = 220;
    const left = 39;
    const right = 39;
    const top = 15;
    const bottom = 34;
    const chartWidth = width - left - right;
    const chartHeight = height - top - bottom;
    const maximumExamples = Math.max(1, ...history.map((item) => Number(item.examples) || 0));
    const x = (index) =>
      history.length === 1
        ? left + chartWidth / 2
        : left + (index / (history.length - 1)) * chartWidth;
    const y = (value) => top + (1 - clamp(value)) * chartHeight;
    const points = (selector) =>
      history.map((item, index) => `${x(index)},${y(selector(item))}`).join(" ");
    const grid = [0, 0.25, 0.5, 0.75, 1]
      .map(
        (tick) => `
          <line class="axis" x1="${left}" y1="${y(tick)}" x2="${width - right}" y2="${y(tick)}"></line>
          <text x="${left - 8}" y="${y(tick) + 3}" text-anchor="end">${Math.round(tick * 100)}</text>
          <text x="${width - right + 8}" y="${y(tick) + 3}" text-anchor="start">${Math.round(tick * maximumExamples)}</text>`,
      )
      .join("");
    const nodes = history
      .map((item, index) => {
        const date = item.generated_at
          ? new Date(item.generated_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
            })
          : `Run ${index + 1}`;
        const examplesRatio = (Number(item.examples) || 0) / maximumExamples;
        return `
          <circle class="coverage-point" cx="${x(index)}" cy="${y(item.evaluability)}" r="4">
            <title>${escapeHtml(item.run_id)}: ${percentage(item.evaluability)} evaluable</title>
          </circle>
          <circle class="examples-point" cx="${x(index)}" cy="${y(examplesRatio)}" r="3.5">
            <title>${escapeHtml(item.run_id)}: ${escapeHtml(item.examples)} examples</title>
          </circle>
          <text x="${x(index)}" y="${height - 9}" text-anchor="middle">${escapeHtml(date)}</text>`;
      })
      .join("");
    target.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="progress-title progress-desc">
        <title id="progress-title">Descriptive evidence progression</title>
        <desc id="progress-desc">Evaluability percentage on the left axis and example count on the right axis over ${history.length} local runs. This is not a regression comparison.</desc>
        ${grid}
        <polyline class="coverage-line" points="${points((item) => item.evaluability)}"></polyline>
        <polyline class="examples-line" points="${points((item) => (Number(item.examples) || 0) / maximumExamples)}"></polyline>
        ${nodes}
      </svg>`;
  }

  function interval(metric) {
    if (!scored(metric) || !metric.interval || !finite(metric.interval.lower)) {
      return '<p class="detail-description">No sampling interval is available.</p>';
    }
    const lower = clamp(metric.interval.lower);
    const upper = clamp(metric.interval.upper);
    const point = clamp(metric.value);
    return `
      <div class="interval" title="${escapeHtml(metric.interval.method)} ${escapeHtml(metric.interval.level * 100)}% interval">
        <span>${percentage(lower)}</span>
        <div class="interval-track">
          <span class="interval-range" style="left:${lower * 100}%;width:${Math.max(0, upper - lower) * 100}%"></span>
          <span class="interval-point" style="left:${point * 100}%"></span>
        </div>
        <span>${percentage(upper)}</span>
      </div>
      <p class="detail-description">${escapeHtml(metric.aggregation)} · n=${escapeHtml(metric.n)} · ${escapeHtml(metric.interval.method)} ${escapeHtml(metric.interval.level * 100)}% interval</p>`;
  }

  function population(metric) {
    const value = metric.population || {};
    const fields = [
      ["Available", value.available],
      ["Selector matched", value.selector_matched],
      ["Eligible", value.eligible],
      ["Scored", value.scored],
    ];
    return `<dl class="definition-list">${fields
      .map(
        ([label, count]) =>
          `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(count ?? "—")}</dd>`,
      )
      .join("")}</dl>`;
  }

  function authority(metric) {
    const reasons = metric.authority?.reasons || [];
    return `
      <div class="state-line">
        <span class="state-badge">${escapeHtml(metric.authority?.level || "unknown")}</span>
        <span>${metric.authority?.can_gate ? "Can gate" : "Cannot gate"}</span>
      </div>
      ${
        reasons.length
          ? `<ul class="detail-list">${reasons
              .map((reason) => `<li>${escapeHtml(String(reason).replaceAll("_", " "))}</li>`)
              .join("")}</ul>`
          : '<p class="detail-description">No authority reasons were provided.</p>'
      }`;
  }

  function diagnostics(metric) {
    const items = metric.diagnostics || [];
    if (!items.length) return '<p class="detail-description">No diagnostic was emitted.</p>';
    const row = (item) => {
      const count = item.count ? ` · ${escapeHtml(item.count)} cases` : "";
      return `<li><strong>${escapeHtml(item.code)}</strong>${count}: ${escapeHtml(item.message)}</li>`;
    };
    return `<ul class="detail-list">${items.map(row).join("")}</ul>`;
  }

  function calls(metric) {
    const items = metric.calls || [];
    if (!items.length) return '<p class="detail-description">No call-level sample is embedded.</p>';
    return `<ul class="call-list">${items
      .slice(0, 12)
      .map(
        (item) => `
          <li class="call-item" title="${escapeHtml(item.example_id)}">
            <span class="call-id">${escapeHtml(compactId(item.example_id))}</span>
            <span class="call-status">${escapeHtml(item.status)}</span>
            <span class="call-value">${finite(item.value) ? percentage(item.value) : "—"}</span>
          </li>`,
      )
      .join("")}</ul>`;
  }

  function comparisonDetail(metric) {
    const comparison = metric.comparison || {};
    if (!comparisonIsValid(metric)) {
      return `<p class="detail-description">No numeric delta. Comparison state: ${escapeHtml(String(comparison.state || data.comparison?.state || "not requested").replaceAll("_", " "))}.</p>`;
    }
    const interval = comparison.interval;
    return `
      <div class="state-line">
        <span class="outcome-badge ${escapeHtml(comparison.outcome)}">${escapeHtml(String(comparison.outcome).replaceAll("_", " "))}</span>
        <span>${escapeHtml(deltaText(metric))} direction-adjusted</span>
      </div>
      <dl class="definition-list">
        <dt>Paired interval</dt>
        <dd>${interval ? `${(interval.lower * 100).toFixed(1)} to ${(interval.upper * 100).toFixed(1)} pp` : "—"}</dd>
        <dt>Shared examples</dt>
        <dd>${escapeHtml(comparison.shared_examples ?? "—")}</dd>
        <dt>Raw delta</dt>
        <dd>${finite(comparison.delta) ? `${(comparison.delta * 100).toFixed(1)} pp` : "—"}</dd>
      </dl>`;
  }

  function judgeDetail(metric) {
    const judge = metric.judge;
    if (!judge) return "";
    const reviews = judge.reviews || [];
    return `
      <section class="judge-section">
        <h3>Judge evidence · ${escapeHtml(judge.calibration || "unknown calibration")}</h3>
        <div class="judge-grid">
          ${reviews
            .map(
              (review) => `
                <article class="judge-card">
                  <div class="judge-meta">
                    <span title="${escapeHtml(review.example_id)}">${escapeHtml(compactId(review.example_id))}</span>
                    <strong>${finite(review.score) ? percentage(review.score) : "—"}</strong>
                  </div>
                  <p>${escapeHtml(review.rationale || "No rationale was retained.")}</p>
                  ${
                    review.violations?.length
                      ? `<ul>${review.violations
                          .map((item) => `<li>${escapeHtml(item)}</li>`)
                          .join("")}</ul>`
                      : ""
                  }
                  <div class="judge-provenance">
                    ${escapeHtml(judge.model_ref || "unknown model")} · rubric ${escapeHtml(judge.rubric_version || "—")}
                    ${review.cache ? ` · cache ${escapeHtml(review.cache)}` : ""}
                    ${finite(review.latency_ms) ? ` · ${escapeHtml(review.latency_ms)} ms` : ""}
                  </div>
                </article>`,
            )
            .join("") || '<p class="detail-description">No judge review detail was retained.</p>'}
        </div>
      </section>`;
  }

  function metricNode(metric) {
    const outcome = comparisonIsValid(metric)
      ? metric.comparison.outcome || "within_noise"
      : "not_comparable";
    const attention = needsAttention(metric);
    const gateActive = ["pass", "fail", "blocked"].includes(metric.gate?.state);
    return `
      <details id="${escapeHtml(slug(metric.name))}" class="metric" data-name="${escapeHtml(
        `${metric.name} ${metric.label} ${metric.workflow} ${(metric.diagnostics || [])
          .map((item) => item.message)
          .join(" ")}`.toLowerCase(),
      )}" data-tier="${escapeHtml(metric.tier || "unspecified")}" data-attention="${attention}" data-gate="${gateActive}">
        <summary>
          <div class="metric-title">
            <span class="tier-badge ${escapeHtml(metric.tier || "unspecified")}">${escapeHtml(metric.tier || "metric")}</span>
            <span class="metric-title-copy">
              <span class="metric-label">${escapeHtml(metric.label || metric.name)}</span>
              <span class="metric-name">${escapeHtml(metric.name)}</span>
            </span>
          </div>
          <div class="metric-measure">
            <strong class="metric-value ${scored(metric) ? "" : "missing"}">${escapeHtml(metricValue(metric))}</strong>
            <div class="score-track" aria-hidden="true"><div class="score-fill" style="width:${scored(metric) ? clamp(metric.value) * 100 : 0}%"></div></div>
          </div>
          <div class="metric-delta ${escapeHtml(outcome)}" title="${escapeHtml(String(metric.comparison?.state || data.comparison?.state || "not requested").replaceAll("_", " "))}">${escapeHtml(deltaText(metric))}</div>
          <div class="metric-evidence">n=${escapeHtml(metric.n ?? 0)}</div>
        </summary>
        <div class="metric-detail">
          <section class="detail-card">
            <h3>Measure</h3>
            <p class="detail-description">${escapeHtml(metric.description || "No construct description was provided.")}</p>
            <div class="state-line">
              <span class="state-badge ${escapeHtml(metric.status)}">${escapeHtml(String(metric.status).replaceAll("_", " "))}</span>
              <span>${escapeHtml(metric.validity || "unknown validity")} · ${escapeHtml(metric.direction || "unknown direction")}</span>
            </div>
            ${interval(metric)}
          </section>
          <section class="detail-card">
            <h3>Population</h3>
            ${population(metric)}
          </section>
          <section class="detail-card">
            <h3>Authority</h3>
            ${authority(metric)}
          </section>
          <section class="detail-card">
            <h3>Comparable change</h3>
            ${comparisonDetail(metric)}
          </section>
          <section class="detail-card">
            <h3>Call evidence</h3>
            ${calls(metric)}
          </section>
          <section class="detail-card">
            <h3>Diagnostics</h3>
            ${diagnostics(metric)}
          </section>
          ${judgeDetail(metric)}
        </div>
      </details>`;
  }

  function renderMetrics() {
    const workflows = [...new Set(data.metrics.map((metric) => metric.workflow || "Other"))];
    byId("metrics-root").innerHTML = workflows
      .map((workflow) => {
        const metrics = data.metrics.filter((metric) => (metric.workflow || "Other") === workflow);
        return `
          <section class="workflow-group" data-workflow="${escapeHtml(workflow)}">
            <div class="workflow-heading">
              <span>${escapeHtml(workflow)}</span>
              <span class="workflow-visible-count">${metrics.length} metrics</span>
            </div>
            ${metrics.map(metricNode).join("")}
          </section>`;
      })
      .join("");
  }

  function applyFilters() {
    const query = byId("metric-search").value.trim().toLowerCase();
    const active = document.querySelector(".filter.active")?.dataset.filter || "all";
    let visibleTotal = 0;
    for (const metric of document.querySelectorAll(".metric")) {
      const matchesQuery = metric.dataset.name.includes(query);
      const matchesFilter =
        active === "all" ||
        (active === "attention" && metric.dataset.attention === "true") ||
        (active === "gates" && metric.dataset.gate === "true") ||
        (active === "judge" && metric.dataset.tier === "judge");
      metric.hidden = !(matchesQuery && matchesFilter);
      if (!metric.hidden) visibleTotal += 1;
    }
    for (const group of document.querySelectorAll(".workflow-group")) {
      const visible = [...group.querySelectorAll(".metric")].filter((item) => !item.hidden);
      group.hidden = visible.length === 0;
      group.querySelector(".workflow-visible-count").textContent = `${visible.length} metrics`;
    }
    byId("metric-count-copy").textContent =
      visibleTotal === data.metrics.length
        ? `${visibleTotal} metrics · open a row for evidence and traceability.`
        : `${visibleTotal} of ${data.metrics.length} metrics shown.`;
  }

  function openMetric(metricName, { updateHash = true } = {}) {
    const target = [...document.querySelectorAll(".metric")].find(
      (item) => item.id === slug(metricName) || item.dataset.name.includes(metricName.toLowerCase()),
    );
    if (!target) return;
    document.querySelector('[data-filter="all"]').click();
    byId("metric-search").value = "";
    applyFilters();
    target.open = true;
    if (updateHash) history.replaceState(null, "", `#${target.id}`);
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.querySelector("summary").focus({ preventScroll: true });
  }

  function bindInteractions() {
    const root = document.documentElement;
    try {
      const savedTheme = localStorage.getItem("evalglass-theme");
      if (["light", "dark", "system"].includes(savedTheme)) root.dataset.theme = savedTheme;
    } catch {
      root.dataset.theme = "system";
    }
    byId("theme-toggle").addEventListener("click", () => {
      const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const currentlyDark =
        root.dataset.theme === "dark" || (root.dataset.theme === "system" && systemDark);
      root.dataset.theme = currentlyDark ? "light" : "dark";
      byId("theme-toggle").textContent = currentlyDark ? "◐" : "◑";
      byId("theme-toggle").setAttribute(
        "aria-label",
        currentlyDark ? "Use dark theme" : "Use light theme",
      );
      try {
        localStorage.setItem("evalglass-theme", root.dataset.theme);
      } catch {
        // Theme still works when local storage is unavailable.
      }
    });
    byId("copy-link").addEventListener("click", async () => {
      const button = byId("copy-link");
      try {
        await navigator.clipboard.writeText(window.location.href);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Use address bar";
      }
      window.setTimeout(() => {
        button.textContent = "Copy link";
      }, 1600);
    });
    byId("metric-search").addEventListener("input", applyFilters);
    for (const button of document.querySelectorAll(".filter")) {
      button.addEventListener("click", () => {
        for (const item of document.querySelectorAll(".filter")) {
          item.classList.remove("active");
          item.setAttribute("aria-pressed", "false");
        }
        button.classList.add("active");
        button.setAttribute("aria-pressed", "true");
        applyFilters();
      });
    }
    byId("attention-list").addEventListener("click", (event) => {
      const button = event.target.closest("[data-open]");
      if (button) openMetric(button.dataset.open);
    });
    for (const metric of document.querySelectorAll(".metric")) {
      metric.addEventListener("toggle", () => {
        if (metric.open) history.replaceState(null, "", `#${metric.id}`);
      });
    }
    if (window.location.hash) {
      const target = document.querySelector(window.location.hash);
      if (target?.classList.contains("metric")) {
        target.open = true;
        window.setTimeout(() => target.scrollIntoView({ block: "center" }), 0);
      }
    }
  }

  renderHero();
  renderKpis();
  renderWorkflows();
  renderAttention();
  renderComparison();
  renderProgression();
  renderMetrics();
  bindInteractions();
  applyFilters();
})();
