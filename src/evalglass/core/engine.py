"""The pure Evaluation Core engine (EG-M0-6b).

``run_evaluation`` composes the whole effect-free pipeline over supplied data:
evaluators -> scores -> aggregation -> provenance/comparability -> authority ->
the single Verdict Engine -> :class:`RunRecord` + :class:`Scorecard`. It performs
no I/O, network, subprocess, clock, or randomness (``CLAUDE.md §8``;
``architecture.md §3``) — the Runtime Harness collects evidence and persists
outputs; the core only computes meaning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from evalglass.core._validation import ContractError
from evalglass.core.aggregation import aggregate
from evalglass.core.authority import AuthorityInputs, resolve_authority
from evalglass.core.clusters import cluster
from evalglass.core.contracts import Diagnostic, EvidenceBundle, Example, Severity
from evalglass.core.decision import DecisionPolicy
from evalglass.core.estimate import Estimate, estimate
from evalglass.core.evaluators import Evaluator, EvaluatorContext
from evalglass.core.population import PopulationSummary
from evalglass.core.provenance import ComparableRunFingerprint, RunFingerprint
from evalglass.core.registry import MetricSpec
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreBatch, ScoreStatus, Validity
from evalglass.core.selector import ExampleSelector
from evalglass.core.verdict import GateInput, VerdictPayload, decide_verdict

#: Sentinel id for the synthetic score a selector-metric emits when it matches no examples.
_SELECTOR_NO_MATCH_ID = "__evalglass_selector_no_match__"


def _validated(score: Score, spec: MetricSpec) -> Score:
    """Fail closed if an evaluator returns a score that violates its metric spec."""
    if score.metric not in spec.emits:
        raise ContractError(
            f"evaluator for '{spec.name}' emitted undeclared score '{score.metric}' "
            f"(declared: {spec.emits})"
        )
    if (
        score.status is ScoreStatus.SCORED
        and score.value is not None
        and spec.score_range is not None
    ):
        low, high = spec.score_range
        if not (low <= score.value <= high):
            raise ContractError(
                f"evaluator for '{spec.name}' returned {score.value} outside declared "
                f"range [{low}, {high}]"
            )
    return score


def _selector_no_match(metric: str) -> Score:
    """The single honest score a selector-metric gets when its selector matched no examples.

    ``non_evaluable`` (never a misleading ``0.0``): the metric could not run because nothing in this
    run belongs to its declared call site. An active gate over it blocks (no measured value) rather
    than passing vacuously; the diagnostic makes the gap visible on the Scorecard.
    """
    return Score(
        metric=metric,
        value=None,
        status=ScoreStatus.NON_EVALUABLE,
        validity=Validity.NOT_APPLICABLE,
        evaluator_version="selector@1",
        example_id=_SELECTOR_NO_MATCH_ID,
        unit_id=_SELECTOR_NO_MATCH_ID,
        diagnostics=[
            Diagnostic(
                code="selector.no_match",
                severity=Severity.INFO,
                message="this metric's applies_to selector matched no examples in this run",
            )
        ],
    )


def _collect(
    plan: MetricPlan, examples: Sequence[Example], evidence: EvidenceBundle
) -> list[Score]:
    """Run a plan's evaluator over its applicable examples, validating + preserving batch refs.

    When the plan carries an :class:`ExampleSelector`, only examples it matches are scored (an
    integrity example always matches). If a selector matches nothing, a single ``non_evaluable``
    score records the gap honestly rather than leaving the metric silently absent.
    """
    context = EvaluatorContext(spec=plan.spec, params=plan.params)
    collected: list[Score] = []
    matched = False
    for example in examples:
        if plan.selector is not None and not plan.selector.matches(example):
            continue
        matched = True
        # Subject identity is stamped here (F1 / ADR 0024), not by evaluators: the
        # engine authoritatively knows which Example/EvalUnit produced each score,
        # so built-ins, host evaluators, judges, and the route-error guard all get
        # consistent example_id/unit_id without any identity plumbing of their own.
        eid, uid = example.example_id, example.unit.unit_id
        result = plan.evaluator(example, context, evidence)
        if isinstance(result, ScoreBatch):
            for member in result.scores:
                # Propagate batch-level shared evidence onto each member so the
                # RunRecord (which stores individual scores) keeps the pointer.
                merged = list(dict.fromkeys([*member.evidence_refs, *result.evidence_refs]))
                stamped = replace(member, evidence_refs=merged, example_id=eid, unit_id=uid)
                collected.append(_validated(stamped, plan.spec))
        else:
            collected.append(_validated(replace(result, example_id=eid, unit_id=uid), plan.spec))
    if plan.selector is not None and not matched:
        collected.append(_selector_no_match(plan.spec.name))
    return collected


@dataclass(frozen=True)
class MetricPlan:
    """One metric's plan for a run: its spec, evaluator, authority inputs, threshold."""

    spec: MetricSpec
    evaluator: Evaluator
    authority: AuthorityInputs
    threshold: float | None = None
    params: dict[str, Any] = field(default_factory=dict)
    #: Additive (M7 T2): a host-owned decision policy. When present, an active gate
    #: decides on the policy statistic (confidence bound + adequacy) over the Estimate;
    #: absent -> the legacy point-vs-threshold path (backward-compatible).
    decision_policy: DecisionPolicy | None = None
    #: Additive (EG-V02-4 / K2): a host-owned example selector. When present the plan scores only
    #: examples the selector matches (an integrity example always matches); absent -> every example
    #: is scored, byte-identical to the pre-selector engine.
    selector: ExampleSelector | None = None


def run_evaluation(
    *,
    run_id: str,
    examples: Sequence[Example],
    evidence: EvidenceBundle,
    plans: Sequence[MetricPlan],
    dimensions: Mapping[str, Any],
    baseline: RunFingerprint | None = None,
    comparison_requested: bool = False,
) -> RunRecord:
    """Run every metric plan over every example and compose an honest RunRecord."""
    all_scores: list[Score] = []
    for plan in plans:
        all_scores.extend(_collect(plan, examples, evidence))

    # Compute comparability up front so authority resolution uses the run's actual
    # baseline state, not a possibly-stale caller-supplied one.
    current = RunFingerprint.of(dimensions)
    comparable = ComparableRunFingerprint(
        current=current, baseline=baseline, requested=comparison_requested
    )

    metrics = []
    estimates: list[Estimate] = []
    authority = {}
    gates: list[GateInput] = []
    for plan in plans:
        aggregated = aggregate(plan.spec.name, all_scores, plan.spec.aggregation)
        # The Estimate carries the same point (it reuses aggregate) plus the honest
        # interval + n_effective + diagnostics — decision-grade uncertainty alpha lacked.
        est = estimate(plan.spec, all_scores)
        estimates.append(est)
        authority_inputs = plan.authority
        if authority_inputs.requires_baseline:
            authority_inputs = replace(authority_inputs, baseline_state=comparable.state)
        resolved = resolve_authority(authority_inputs)
        excluded = sum(aggregated.status_counts.values()) - aggregated.included_count
        metrics.append(aggregated)
        authority[plan.spec.name] = resolved
        gates.append(
            GateInput(
                metric=plan.spec.name,
                resolved=resolved,
                value=aggregated.value,
                threshold=plan.threshold,
                direction=plan.spec.direction,
                excluded_count=excluded,
                estimate=est,
                decision_policy=plan.decision_policy,
            )
        )

    verdict: VerdictPayload = decide_verdict(gates)
    scorecard = Scorecard(
        verdict=verdict,
        metrics=metrics,
        authority=authority,
        baseline_state=comparable.state,
        estimates=estimates,
        # P3 (ADR 0047): group the run's failing/non-scored items by shared diagnostic cause. A pure
        # projection of all_scores (recomputed by _verify_consistency); empty when no diagnostics.
        clusters=cluster(all_scores),
        # D3: per-metric terminal population accounting (scored_valid/non_evaluable/blocked/skipped/
        # error). The Harness enriches each with the plan's pre-effect coverage after this returns;
        # the core sets only what it can verify from the raw scores.
        populations=[PopulationSummary.from_scores(plan.spec.name, all_scores) for plan in plans],
    )
    return RunRecord(
        run_id=run_id,
        scorecard=scorecard,
        scores=all_scores,
        provenance=current,
        comparable=comparable,
    )
