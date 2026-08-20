"""Judge-evidence collection — the effectful seam between metrics and a JudgeModel (EG-M4-1b).

Collection is **plan-driven**: it iterates the eligible judge effects the
:class:`EvaluationPlan` resolved *before* any effect, never the Cartesian product of every judge
metric and every example. A selector-mismatched subject is therefore never serialised into a
request, and applicability has one implementation (the plan, from ``ExampleSelector.matches``) —
not a second copy inside a host judge. Collection stays **policy-aware**: a subject whose data
policy forbids egress (``policy_decision == denied``) is never sent to the judge, recorded instead
as a ``MISSING`` evidence with a diagnostic — the same fail-closed egress rule the M2 replay
subprocess uses. Each ``JudgeResult`` becomes a core ``JudgeEvidence`` (adding the rubric/prompt/
model refs and the response fingerprint); the effect-free judge evaluator (EG-M4-4) parses it into
a Score. This module owns the effect, never the meaning. It returns the set of *handled* effect
ids so the runner can reconcile planned vs executed effects.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from evalglass.core import Diagnostic, Example, JudgeEvidence, JudgeEvidenceStatus
from evalglass.harness.errors import setup_diagnostic
from evalglass.harness.judge_execution import JudgeExecutor
from evalglass.harness.plan import EvaluationPlan, PolicyDecision
from evalglass.harness.ports import JudgeModel, JudgeRequest, JudgeResult
from evalglass.harness.rubric import RubricRef


def _fingerprint(raw: str | None) -> str | None:
    if raw is None:
        return None
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_evidence(
    result: JudgeResult,
    request: JudgeRequest,
    ref: RubricRef | None,
    *,
    cache_state: str | None = None,
    attempts: int | None = None,
) -> JudgeEvidence:
    return JudgeEvidence(
        example_id=result.example_id,
        metric=result.metric,
        status=result.status,
        parsed_value=result.parsed_value,
        raw_response=result.raw_response,
        rationale=result.rationale,
        rubric_ref=request.rubric_ref,
        rubric_version=ref.version if ref is not None else None,
        prompt_ref=request.prompt_ref,
        model_ref=request.model_ref,
        parser_version=ref.parser_version if ref is not None else None,
        response_fingerprint=_fingerprint(result.raw_response),
        tokens=result.tokens,
        cost=result.cost,
        latency_ms=result.latency_ms,
        facets=dict(result.facets),
        violations=list(result.violations),
        citations=list(result.citations),
        refusal_reason=result.refusal_reason,
        cache_state=cache_state,
        attempts=attempts,
        diagnostics=result.diagnostics,
    )


def collect_judge_evidence(
    judge: JudgeModel,
    plan: EvaluationPlan,
    example_by_subject: Mapping[str, Example],
    rubrics: Mapping[str, RubricRef] | None = None,
    *,
    executor: JudgeExecutor | None = None,
) -> tuple[list[JudgeEvidence], list[Diagnostic], list[str]]:
    """Collect judge evidence for the plan's eligible judge effects only.

    Iterates ``plan.judge_effects()`` — exactly the selector-matched, non-integrity subject-metric
    pairs the plan resolved before any effect — so the judge is invoked once per eligible pair, and
    a mismatched or integrity subject is never built into a request. Data policy is enforced before
    the call: a ``denied`` effect produces a typed ``MISSING`` evidence, never a provider call. When
    an ``executor`` is given (C3), the actual dispatch runs under its cache/budget/retry policy and
    the resulting cache state and attempts are recorded on the evidence; without one, each request
    is dispatched directly (byte-identical to the pre-C3 path). Returns ``(evidence, diagnostics,
    handled_effect_ids)``; each planned judge effect is handled exactly once.
    """
    rubric_map = rubrics or {}
    diagnostics: list[Diagnostic] = []
    handled: list[str] = []
    # First pass: one ordered entry per effect — a ready denied ``JudgeEvidence``, or a
    # ``(request, ref)`` to dispatch — so the assembled evidence stays in deterministic order.
    entries: list[JudgeEvidence | tuple[JudgeRequest, RubricRef | None]] = []
    for effect in plan.judge_effects():
        metric_name = effect.metric or ""
        example = example_by_subject[effect.subject_id]
        ref = rubric_map.get(metric_name)
        handled.append(effect.effect_id)
        if effect.policy_decision is PolicyDecision.DENIED:
            denied = _egress_denied(example, metric_name)
            diagnostics.extend(denied.diagnostics)
            entries.append(denied)
        else:
            entries.append((_build_request(example, metric_name, ref), ref))
    # Dispatch the non-denied requests (in entry order) and assemble evidence back in order.
    requests = [entry[0] for entry in entries if isinstance(entry, tuple)]
    outcomes = iter(_dispatch(judge, executor, requests))
    evidence: list[JudgeEvidence] = []
    for entry in entries:
        if isinstance(entry, JudgeEvidence):
            evidence.append(entry)
            continue
        request, ref = entry
        result, cache_state, attempts = next(outcomes)
        evidence.append(
            _to_evidence(
                result,
                request,
                ref,
                cache_state=cache_state if cache_state in ("hit", "miss") else None,
                attempts=attempts or None,
            )
        )
        diagnostics.extend(result.diagnostics)
    return evidence, diagnostics, handled


def _egress_denied(example: Example, metric: str) -> JudgeEvidence:
    """Typed MISSING evidence for a data-policy-forbidden subject — no judge call is made."""
    diag = setup_diagnostic(
        "judge_egress_forbidden",
        f"data policy forbids host egress for example {example.example_id!r}; "
        "the judge was not called",
        location=example.example_id,
    )
    return JudgeEvidence(
        example_id=example.example_id,
        metric=metric,
        status=JudgeEvidenceStatus.MISSING,
        diagnostics=[diag],
    )


def _build_request(example: Example, metric: str, ref: RubricRef | None) -> JudgeRequest:
    return JudgeRequest(
        example_id=example.example_id,
        metric=metric,
        input=example.input,
        output=example.output,
        reference=example.reference,
        context=example.context,
        rubric_ref=ref.path if ref is not None else None,
        prompt_ref=ref.prompt_ref if ref is not None else None,
        model_ref=ref.model_ref if ref is not None else None,
    )


def _dispatch(
    judge: JudgeModel, executor: JudgeExecutor | None, requests: list[JudgeRequest]
) -> list[tuple[JudgeResult, str | None, int | None]]:
    """Dispatch requests via the executor (cache/budget/retry) or directly, keeping order.

    Returns ``(result, cache_state, attempts)`` per request. The direct path (no executor) leaves
    cache_state/attempts unset, so a run without an execution policy is byte-identical to pre-C3.
    """
    if executor is None:
        return [(judge.judge(request), None, None) for request in requests]
    return [
        (outcome.result, outcome.cache_state.value, outcome.attempts)
        for outcome in executor.run(requests)
    ]
