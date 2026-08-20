"""``evalglass preflight`` + ``run --dry-run`` preflight — problems and cost before any effect.

Preflight and dry-run are **side-effect-free by default**: they resolve the same
:class:`~evalglass.harness.plan.EvaluationPlan` a real ``run`` would (via
:func:`~evalglass.harness.runner.preflight` with lanes off), and report — per metric — the
selector-matched/eligible population, the planned judge and replay request counts, the egress
decision, and whether a gate *would* be authorized if measured. No provider call, judge call, task
replay, baseline promotion, or authority mutation happens. Missing credentials
are reported by environment-variable *name* only; cost is labelled an upper-bound estimate, never an
invoice. Text and JSON are two projections of one typed :class:`PreflightReport` so their totals
reconcile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evalglass.core import resolve_authority
from evalglass.core.authority import ResolvedAuthority
from evalglass.core.contracts import Diagnostic
from evalglass.harness.config import MetricConfig, RuntimeConfig
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.evaluator_loader import load_evaluator
from evalglass.harness.plan import PlannedMetric
from evalglass.harness.runner import _metric_authority_inputs, preflight

#: Versioned schema tag for the ``run-plan.json`` preflight projection and JSON output.
PREFLIGHT_SCHEMA = "evalglass.preflight/1"


@dataclass(frozen=True)
class MetricPreflight:
    """Per-metric preflight facts — population, planned effects, and gate readiness."""

    metric: str
    available: int
    selector_matched: int
    eligible: int
    excluded: dict[str, int]
    planned_judge_requests: int
    prerequisites: list[str]
    metric_status: str
    threshold_approval: str
    judge_calibration: str | None
    would_gate_if_measured: bool
    authority_reasons: list[str]
    #: Additive (D1): the metric's resolved source bindings (name + role), or ``None`` when unbound.
    source_bindings: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "available": self.available,
            "selector_matched": self.selector_matched,
            "eligible": self.eligible,
            "excluded": dict(self.excluded),
            "planned_judge_requests": self.planned_judge_requests,
            "prerequisites": list(self.prerequisites),
            "metric_status": self.metric_status,
            "threshold_approval": self.threshold_approval,
            "would_gate_if_measured": self.would_gate_if_measured,
            "authority_reasons": list(self.authority_reasons),
        }
        if self.judge_calibration is not None:
            out["judge_calibration"] = self.judge_calibration
        if self.source_bindings is not None:
            out["source_bindings"] = [dict(b) for b in self.source_bindings]
        return out


@dataclass(frozen=True)
class PreflightReport:
    """One typed preflight report; text and JSON are projections of it."""

    run_id: str
    subjects: int
    planned_judge_requests: int
    planned_replay_requests: int
    judge_adapter: str | None
    plan_fingerprint: str
    metrics: list[MetricPreflight]
    issues: list[Diagnostic] = field(default_factory=list)
    #: Judge execution preview (C3): cache mode + candidate count, configured budgets, and a
    #: conservative upper-bound on output tokens / cost — all with no provider call. Present only
    #: when the host configured a judge execution policy.
    judge_execution: dict[str, Any] | None = None
    schema: str = PREFLIGHT_SCHEMA

    @property
    def has_blocking_issue(self) -> bool:
        return any(d.severity.value == "error" for d in self.issues)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": self.schema,
            "run_id": self.run_id,
            "subjects": self.subjects,
            "planned_effects": {
                "judge_requests": self.planned_judge_requests,
                "replay_requests": self.planned_replay_requests,
            },
            "judge_adapter": self.judge_adapter,
            "plan_fingerprint": self.plan_fingerprint,
            "metrics": [m.to_dict() for m in self.metrics],
            "issues": [d.to_dict() for d in self.issues],
        }
        if self.judge_execution is not None:
            out["judge_execution"] = dict(self.judge_execution)
        return out

    def render_text(self) -> str:
        lines = [
            f"preflight: {self.run_id} ({self.schema})",
            f"  subjects loaded: {self.subjects}",
            f"  planned external requests (upper bound estimate): "
            f"judge={self.planned_judge_requests} replay={self.planned_replay_requests}",
            f"  judge adapter: {self.judge_adapter or 'none'}",
            f"  plan fingerprint: {self.plan_fingerprint}",
            "  metrics:",
        ]
        lines.extend(_metric_line(m) for m in self.metrics)
        lines.extend(self._judge_execution_lines())
        if self.issues:
            lines.append("  issues:")
            for d in self.issues:
                loc = f" @ {d.location}" if d.location else ""
                lines.append(f"    [{d.severity.value}] {d.code}: {d.message}{loc}")
        else:
            lines.append("  issues: none")
        return "\n".join(lines)

    def _judge_execution_lines(self) -> list[str]:
        if self.judge_execution is None:
            return []
        je = self.judge_execution
        ub = je.get("upper_bound", {})
        cost = ub.get("cost")
        cost_str = f"{cost}" if cost is not None else "unavailable (no cost table)"
        return [
            f"  judge execution: cache={je.get('cache_mode')} "
            f"candidates={je.get('cache_candidates')} "
            f"max_output_tokens<={ub.get('output_tokens')} cost<={cost_str}"
        ]


def _metric_line(m: MetricPreflight) -> str:
    """One metric's preflight line — population, planned effects, gate readiness, and bindings."""
    gate = "gate=would-gate-if-measured" if m.would_gate_if_measured else "gate=none"
    excl = (
        " excluded=" + ",".join(f"{k}:{v}" for k, v in sorted(m.excluded.items()))
        if m.excluded
        else ""
    )
    reasons = f" [{', '.join(m.authority_reasons)}]" if m.authority_reasons else ""
    bindings = (
        " sources=" + ",".join(f"{b['name']}:{b['role']}" for b in m.source_bindings)
        if m.source_bindings
        else ""
    )
    return (
        f"    - {m.metric}: available={m.available} matched={m.selector_matched} "
        f"eligible={m.eligible}{excl} judge_req={m.planned_judge_requests} "
        f"status={m.metric_status} {gate}{reasons}{bindings}"
    )


def _evaluator_issue(metric: MetricConfig, root: Path) -> Diagnostic | None:
    """Report (not raise) an evaluator that cannot be loaded — a preflight issue, not an effect."""
    ref = metric.spec.evaluator_ref
    try:
        load_evaluator(ref, root)
    except SetupError as exc:
        return exc.diagnostic
    except Exception as exc:  # preflight reports any load failure as a typed issue, never a crash
        return setup_diagnostic(
            "evaluator_load_failed",
            f"evaluator {ref!r} for {metric.spec.name!r} failed to load: {exc}",
            location=ref,
        )
    return None


def report_preflight(config: RuntimeConfig, root: Path) -> PreflightReport:
    """Build the side-effect-free preflight report (no provider/judge/replay/egress)."""
    pf = preflight(config, root, run_lanes=False)
    plan = pf.plan
    planned_by_metric = {pm.metric: pm for pm in plan.metrics}

    issues: list[Diagnostic] = list(pf.route_diagnostics)
    metrics: list[MetricPreflight] = []
    for metric in pf.effective_metrics:
        issue = _evaluator_issue(metric, root)
        if issue is not None:
            issues.append(issue)
        # D2: preview the metric's authority over the evidence it actually consumes (bound), or the
        # conservative run-global worst (unbound) — the same resolution the real run uses.
        resolved = resolve_authority(
            _metric_authority_inputs(metric, config, pf.lane_trace_policies)
        )
        metrics.append(_metric_preflight(metric, planned_by_metric.get(metric.spec.name), resolved))

    return PreflightReport(
        run_id=config.run_id,
        subjects=len(pf.loaded),
        planned_judge_requests=len(plan.judge_effects()),
        planned_replay_requests=len(plan.replay_effects()),
        judge_adapter=config.judge.adapter if config.judge is not None else None,
        plan_fingerprint=plan.fingerprint(),
        metrics=metrics,
        issues=issues,
        judge_execution=_judge_execution_preview(config, len(plan.judge_effects())),
    )


def _metric_preflight(
    metric: MetricConfig, pm: PlannedMetric | None, resolved: ResolvedAuthority
) -> MetricPreflight:
    """Project one metric + its plan ledger + resolved authority into a ``MetricPreflight``."""
    return MetricPreflight(
        metric=metric.spec.name,
        available=pm.available if pm else 0,
        selector_matched=pm.selector_matched if pm else 0,
        eligible=pm.eligible if pm else 0,
        excluded=dict(pm.excluded) if pm else {},
        planned_judge_requests=len(pm.effect_ids) if pm else 0,
        prerequisites=list(metric.spec.required_evidence),
        metric_status=metric.metric_status.value,
        threshold_approval=metric.threshold_approval.value,
        judge_calibration=(
            metric.judge_calibration.value if metric.judge_calibration is not None else None
        ),
        would_gate_if_measured=resolved.can_gate,
        authority_reasons=list(resolved.reasons),
        source_bindings=pm.source_bindings if pm else None,
    )


def _judge_execution_preview(config: RuntimeConfig, planned_requests: int) -> dict[str, Any] | None:
    """A side-effect-free preview of cache mode, budgets, and conservative token/cost upper bounds.

    Reports the planned judge requests as cache candidates and, from the configured decoding limit,
    an upper bound on output tokens; cost is estimated only from a host-supplied cost table (else
    labelled unavailable). No provider call, no cache read.
    """
    judge = config.judge
    if judge is None or judge.execution is None:
        return None
    policy = judge.execution
    output_tokens_ub = planned_requests * judge.max_output_tokens
    cost_ub = policy.cost_table.estimate(0, output_tokens_ub)
    return {
        "cache_mode": policy.cache_mode.value,
        "cache_candidates": planned_requests,
        "budget": {
            "max_requests": policy.max_requests,
            "max_total_tokens": policy.max_total_tokens,
            "max_cost": policy.max_cost,
            "max_wall_seconds": policy.max_wall_seconds,
        },
        "upper_bound": {
            "output_tokens": output_tokens_ub,
            "cost": cost_ub,
            "cost_basis": policy.cost_table.label if policy.cost_table.available else "unavailable",
        },
    }
