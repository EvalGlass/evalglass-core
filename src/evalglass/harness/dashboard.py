"""Dashboard projection — a typed, score-neutral view model for the diagnostic report (Epic E / E1).

This module builds one versioned projection (``evalglass.dashboard/1``) from the typed primary
artifacts (``Scorecard`` + ``RunRecord``) plus host-owned, score-neutral display metadata. It is a
**pure projection**: it copies verdict, authority, gate, population, estimate, and comparison facts
straight from the typed contracts and never recomputes any of them. Specifically it:

* imports no Verdict Engine and no authority resolver — the verdict, gate state, and per-metric
  authority are copied from ``Scorecard`` fields, never re-decided here;
* performs no aggregate subtraction — a numeric delta comes only from the typed
  ``Scorecard.comparison`` (D4), never from ``current - previous`` on aggregate values;
* infers no workflow, tier, or label from a metric name or an authority reason string — those come
  from declared display metadata, with a *typed* fallback (tier derives from the metric's declared
  lens/evaluator, a contract field, not a name heuristic);
* renders a non-scored or invalid metric as absence (``value`` is ``null``), never a fabricated 0.

The renderer (``report_html``) and the Markdown report consume these same facts, so the two surfaces
cannot drift. Presentation metadata carries no authority: an attention flag, a label, or a workflow
name can never change a score, a fingerprint, the verdict, or the CI exit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from evalglass.core import AggregatedMetric, RunRecord, Scorecard
from evalglass.core.contracts import JudgeEvidence
from evalglass.core.population import PopulationSummary
from evalglass.core.registry import Lens, MetricSpec
from evalglass.harness.config import MetricConfig, MetricDisplay, RuntimeConfig
from evalglass.harness.report import gate_state

#: The versioned public projection contract this module emits.
DASHBOARD_SCHEMA = "evalglass.dashboard/1"

#: The single neutral workflow a metric falls back to when the host declares no group. Deterministic
#: and name-free: undeclared metrics group together rather than being split on their name.
NEUTRAL_WORKFLOW = "Ungrouped"

#: Cap on call-level rows embedded per metric, so a large run does not bloat the artifact; the
#: dashboard discloses how many rows were omitted (E3 AC9). Callers see the full population counts.
_MAX_CALLS_PER_METRIC = 200

_VERDICT_DESC: dict[str, str] = {
    "informational": (
        "No metric has active gating authority. These measurements are evidence for review, "
        "not a quality pass."
    ),
    "pass": "Every active gate cleared its approved decision rule.",
    "fail": "At least one active gate is validly measured below its approved threshold.",
    "blocked": "An active gate could not make an honest quality claim.",
}


@dataclass(frozen=True)
class DashboardMeta:
    """Run labels the Scorecard does not carry (rendered as-is, never authority)."""

    run_id: str = ""
    generated_at: str = ""
    application: str = ""
    source_label: str = ""


def project_run(
    scorecard: Scorecard,
    record: RunRecord,
    *,
    config: RuntimeConfig | None,
    meta: DashboardMeta,
    history: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the ``evalglass.dashboard/1`` projection from typed artifacts + display data."""
    metric_configs = {mc.spec.name: mc for mc in config.metrics} if config is not None else {}
    estimates = {e.metric: e for e in scorecard.estimates}
    populations = {p.metric: p for p in scorecard.populations}
    scores_by_metric: dict[str, list[Any]] = {}
    for score in record.scores:
        scores_by_metric.setdefault(score.metric, []).append(score)
    evidence_by_metric: dict[str, list[JudgeEvidence]] = {}
    for ev in record.evidence:
        evidence_by_metric.setdefault(ev.metric, []).append(ev)
    deltas = _comparable_deltas(scorecard)

    metrics = [
        _metric_view(
            agg,
            metric_configs.get(agg.metric),
            scorecard=scorecard,
            estimate=estimates.get(agg.metric),
            population=populations.get(agg.metric),
            delta=deltas.get(agg.metric),
            scores=scores_by_metric.get(agg.metric, []),
            evidence=evidence_by_metric.get(agg.metric, []),
        )
        for agg in scorecard.metrics
    ]
    metrics.sort(key=_metric_order)

    payload: dict[str, Any] = {
        "schema": DASHBOARD_SCHEMA,
        "run": {
            "id": meta.run_id,
            "generated_at": meta.generated_at,
            "application": meta.application,
            "source_label": meta.source_label,
        },
        "verdict": _verdict(scorecard),
        "authority": _authority_summary(scorecard, config),
        "comparison": _comparison_summary(scorecard),
        "summary": _summary(scorecard, record),
        "metrics": metrics,
    }
    if history:
        payload["history"] = [dict(h) for h in history]
    if (
        config is not None
        and config.dashboard is not None
        and config.dashboard.composite is not None
    ):
        # A host-declared, versioned composite is the ONLY licensed overall score. Projected as
        # declared (never computed here); the dashboard shows coverage, never an implicit mean.
        payload["composite"] = dict(config.dashboard.composite)
    return payload


def _verdict(scorecard: Scorecard) -> dict[str, Any]:
    state = scorecard.verdict.verdict.value
    return {
        "state": state,
        "description": _VERDICT_DESC.get(state, ""),
        "ci_should_fail": scorecard.verdict.ci_should_fail,
    }


def _comparable_deltas(scorecard: Scorecard) -> dict[str, Any]:
    comparison = scorecard.comparison
    if comparison is None or comparison.comparison is None:
        return {}
    return dict(comparison.comparison.deltas)


def _authority_summary(scorecard: Scorecard, config: RuntimeConfig | None) -> dict[str, Any]:
    verdict = scorecard.verdict
    active_gates = (
        len(verdict.passing_gates) + len(verdict.failing_gates) + len(verdict.blocked_gates)
    )
    out: dict[str, Any] = {"active_gates": active_gates}
    if config is not None:
        out["dataset"] = _worst_dataset_label(config)
        out["thresholds"] = _worst_threshold_label(config)
        out["judges"] = _worst_judge_label(config)
    else:
        # Artifact-only rebuild: summarize from the typed authority reason codes already on the
        # Scorecard (the resolver's structured output, not free prose).
        reasons = {r for auth in scorecard.authority.values() for r in auth.reasons}
        out["dataset"] = "proposed" if any("dataset_proposed" in r for r in reasons) else "unknown"
        out["thresholds"] = (
            "proposed" if any("threshold_proposed" in r for r in reasons) else "unknown"
        )
        out["judges"] = "uncalibrated" if any("judge" in r for r in reasons) else "not configured"
    return out


def _worst_dataset_label(config: RuntimeConfig) -> str:
    statuses = {d.status.value for d in config.datasets}
    for worst in ("retired", "proposed"):
        if worst in statuses:
            return worst
    return "validated" if statuses else "unknown"


def _worst_threshold_label(config: RuntimeConfig) -> str:
    approvals = {mc.threshold_approval.value for mc in config.metrics}
    return "proposed" if "proposed" in approvals else "approved"


def _worst_judge_label(config: RuntimeConfig) -> str:
    calibrations = {
        mc.judge_calibration.value for mc in config.metrics if mc.judge_calibration is not None
    }
    if not calibrations:
        return "not configured"
    for worst in ("drifted", "retired", "uncalibrated", "calibrating"):
        if worst in calibrations:
            return "uncalibrated" if worst in {"uncalibrated", "calibrating"} else worst
    return "calibrated"


def _comparison_summary(scorecard: Scorecard) -> dict[str, Any]:
    comparison = scorecard.comparison
    if comparison is None:
        state = (
            scorecard.baseline_state.value
            if scorecard.baseline_state is not None
            else ("comparison_not_requested")
        )
        return {"state": state, "changed_dimensions": []}
    out: dict[str, Any] = {
        "state": comparison.state.value,
        "changed_dimensions": list(comparison.changed_dimensions),
    }
    if comparison.baseline_run_id is not None:
        out["baseline_run_id"] = comparison.baseline_run_id
    if comparison.comparison is not None and comparison.comparison.deltas:
        shared = max((d.n_paired for d in comparison.comparison.deltas.values()), default=0)
        out["shared_examples"] = shared
    return out


def _summary(scorecard: Scorecard, record: RunRecord) -> dict[str, Any]:
    scored = sum(1 for m in scorecard.metrics if m.value is not None and m.included_count > 0)
    examples = len({s.example_id for s in record.scores if s.example_id})
    return {
        "metrics_total": len(scorecard.metrics),
        "metrics_scored": scored,
        "examples": examples,
        "call_scores": len(record.scores),
        "diagnostics": len(scorecard.clusters),
    }


def _metric_order(view: Mapping[str, Any]) -> tuple[int, str, str]:
    order = view.get("order")
    order_key = order if isinstance(order, int) else 1_000_000
    return (order_key, str(view.get("workflow") or ""), str(view.get("name") or ""))


def _metric_view(
    agg: AggregatedMetric,
    mc: MetricConfig | None,
    *,
    scorecard: Scorecard,
    estimate: Any,
    population: PopulationSummary | None,
    delta: Any,
    scores: list[Any],
    evidence: list[JudgeEvidence],
) -> dict[str, Any]:
    name = agg.metric
    display = mc.display if mc is not None else None
    spec = mc.spec if mc is not None else None
    status, validity, value = _metric_state(agg, population)
    view: dict[str, Any] = {
        "name": name,
        "label": _label(display, name),
        "description": _text(display.description if display else None),
        "workflow": _workflow(display),
        "tier": _tier(display, spec),
        "direction": spec.direction.value if spec is not None else "unspecified",
        "status": status,
        "validity": validity,
        "value": value,
        "aggregation": agg.aggregation.value,
        "n": estimate.n_effective if estimate is not None else 0,
        "interval": _interval(estimate),
        "population": _population(population),
        "authority": _authority(scorecard, name),
        "gate": _gate(scorecard, name, mc),
        "comparison": _metric_comparison(scorecard, delta),
        "diagnostics": _diagnostics(scorecard, name),
        "calls": _calls(scores),
    }
    if len(scores) > _MAX_CALLS_PER_METRIC:
        view["calls_omitted"] = len(scores) - _MAX_CALLS_PER_METRIC
    judge = _judge(name, evidence, scorecard)
    if judge is not None:
        view["judge"] = judge
    attention = _attention(display, value)
    if attention is not None:
        view["attention"] = attention
    if display is not None and display.order is not None:
        view["order"] = display.order
    _attach_links(view, display)
    return view


def _metric_state(
    agg: AggregatedMetric, population: PopulationSummary | None
) -> tuple[str, str, float | None]:
    """The metric's display status/validity/value — scored only when it produced a value."""
    if agg.value is not None and agg.included_count > 0:
        return "scored", "valid", agg.value
    # Non-scored: pick the terminal state from the typed population counts, worst first. Never a 0.
    if population is not None:
        if population.error:
            return "error", "invalid", None
        if population.blocked:
            return "blocked", "not_measured", None
        if population.non_evaluable:
            return "non_evaluable", "not_measured", None
        if population.skipped:
            return "skipped", "not_applicable", None
    return "non_evaluable", "not_measured", None


def _label(display: MetricDisplay | None, name: str) -> str:
    if display is not None and display.label:
        return display.label
    return name


def _text(value: str | None) -> str:
    return value or ""


def _workflow(display: MetricDisplay | None) -> str:
    if display is not None and display.workflow:
        return display.workflow
    return NEUTRAL_WORKFLOW


def _tier(display: MetricDisplay | None, spec: MetricSpec | None) -> str:
    """The metric's tier: declared, else a typed fallback from the lens/evaluator (never a name)."""
    if display is not None and display.tier:
        return display.tier
    if spec is None:
        return "metric"
    if "judge" in spec.required_evidence or spec.evaluator_ref.startswith("judge_score"):
        return "judge"
    if spec.lens is Lens.REFERENCE:
        return "reference"
    return "runtime"


def _interval(estimate: Any) -> dict[str, Any] | None:
    if estimate is None or estimate.interval is None:
        return None
    iv = estimate.interval
    return {
        "lower": iv.lower,
        "upper": iv.upper,
        "level": iv.level,
        "method": iv.method.value,
    }


def _population(population: PopulationSummary | None) -> dict[str, Any]:
    if population is None:
        return {}
    return {
        "available": population.available,
        "selector_matched": population.selector_matched,
        "eligible": population.eligible,
        "scored": population.scored_valid,
    }


def _authority(scorecard: Scorecard, name: str) -> dict[str, Any]:
    auth = scorecard.authority.get(name)
    if auth is None:
        return {"level": "unknown", "can_gate": False, "reasons": []}
    return {"level": auth.level.value, "can_gate": auth.can_gate, "reasons": list(auth.reasons)}


def _gate(scorecard: Scorecard, name: str, mc: MetricConfig | None) -> dict[str, Any]:
    state = gate_state(scorecard, name)
    threshold: float | None = None
    statistic: str | None = None
    if mc is not None and state != "informational":
        threshold = mc.threshold
        if mc.decision_policy is not None:
            statistic = mc.decision_policy.effective_statistic().value
    return {"state": state, "threshold": threshold, "decision_statistic": statistic}


def _metric_comparison(scorecard: Scorecard, delta: Any) -> dict[str, Any]:
    """The metric's typed paired comparison — a numeric delta only when comparable (D4)."""
    comparison = scorecard.comparison
    state = comparison.state.value if comparison is not None else "comparison_not_requested"
    if delta is None:
        return {
            "state": state,
            "delta": None,
            "direction_adjusted_delta": None,
            "interval": None,
            "outcome": "not_evaluable",
            "shared_examples": 0,
        }
    interval = None
    if delta.interval is not None:
        interval = {"lower": delta.interval.lower, "upper": delta.interval.upper}
    return {
        "state": "comparable",
        "delta": delta.delta,
        "direction_adjusted_delta": delta.direction_adjusted_delta,
        "interval": interval,
        "outcome": delta.outcome.value,
        "shared_examples": delta.n_paired,
    }


def _diagnostics(scorecard: Scorecard, name: str) -> list[dict[str, Any]]:
    return [
        {"code": c.code, "severity": c.severity.value, "message": c.message, "count": c.count}
        for c in scorecard.clusters
        if c.metric == name
    ]


def _calls(scores: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for score in scores[:_MAX_CALLS_PER_METRIC]:
        if score.example_id is None:
            continue
        out.append(
            {"example_id": score.example_id, "status": score.status.value, "value": score.value}
        )
    return out


def _judge(name: str, evidence: list[JudgeEvidence], scorecard: Scorecard) -> dict[str, Any] | None:
    if not evidence:
        return None
    head = evidence[0]
    reviews = [_review(ev) for ev in evidence]
    judge: dict[str, Any] = {
        "calibration": _judge_calibration(scorecard, name),
        "reviews": reviews,
    }
    for key, value in (
        ("model_ref", head.model_ref),
        ("rubric_ref", head.rubric_ref),
        ("rubric_version", head.rubric_version),
        ("prompt_ref", head.prompt_ref),
        ("parser_version", head.parser_version),
    ):
        if value is not None:
            judge[key] = value
    return judge


def _review(ev: JudgeEvidence) -> dict[str, Any]:
    review: dict[str, Any] = {"example_id": ev.example_id, "score": ev.parsed_value}
    if ev.rationale is not None:
        review["rationale"] = ev.rationale
    if ev.violations:
        review["violations"] = list(ev.violations)
    if ev.facets:
        review["facets"] = dict(ev.facets)
    if ev.cache_state is not None:
        review["cache"] = ev.cache_state
    if ev.latency_ms is not None:
        review["latency_ms"] = ev.latency_ms
    return review


def _judge_calibration(scorecard: Scorecard, name: str) -> str:
    auth = scorecard.authority.get(name)
    reasons = list(auth.reasons) if auth is not None else []
    if any("judge_drifted" in r or "drifted" in r for r in reasons):
        return "drifted"
    if any("judge_calibrated" in r for r in reasons):
        return "calibrated"
    if any("judge" in r for r in reasons):
        return "uncalibrated"
    return "unknown"


def _attention(display: MetricDisplay | None, value: float | None) -> dict[str, Any] | None:
    """Whether a host attention rule flags this metric — presentation only, never a gate."""
    if display is None or display.attention is None or value is None:
        return None
    rule = display.attention
    flagged = (rule.below is not None and value < rule.below) or (
        rule.above is not None and value > rule.above
    )
    if not flagged:
        return None
    out: dict[str, Any] = {"flagged": True, "kind": "host_rule"}
    if rule.note:
        out["note"] = rule.note
    return out


def _attach_links(view: dict[str, Any], display: MetricDisplay | None) -> None:
    if display is None:
        return
    links = {
        key: value
        for key, value in (
            ("docs_url", display.docs_url),
            ("owner", display.owner),
            ("source_url", display.source_url),
        )
        if value is not None
    }
    if links:
        view["links"] = links
