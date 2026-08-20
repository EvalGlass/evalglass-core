"""Built-in: judge_score — parse host-collected judge evidence into a Score (EG-M4-4).

The Runtime Harness collects judge evidence (an effect); this **effect-free** built-in reads
``evidence.judge_evidence`` for the example + metric and turns it into a ``Score``. A judge
call is an effect, but parsing its evidence is *meaning*, so it lives in the core. A missing,
timed-out, errored, or unparseable judge response is **never** a ``0.0`` (CLAUDE.md §9): a
usable value is ``scored``; an absent/unavailable response is ``blocked``; an unparseable one
is ``error`` — each carrying typed diagnostics. Domain-neutral and deterministic.
"""

from __future__ import annotations

from typing import Any

from evalglass.core.contracts import (
    Diagnostic,
    EvidenceBundle,
    Example,
    JudgeEvidence,
    JudgeEvidenceStatus,
    Severity,
)
from evalglass.core.evaluators import EvaluatorContext
from evalglass.core.scores import Score, ScoreStatus, Validity

VERSION = "judge_score@1"

# A failed/absent judge response cannot be honestly scored; a required judge gate blocks.
_BLOCKING = frozenset(
    {
        JudgeEvidenceStatus.MISSING,
        JudgeEvidenceStatus.TIMEOUT,
        JudgeEvidenceStatus.PROVIDER_ERROR,
    }
)
_PROVENANCE_FIELDS = (
    "rubric_ref",
    "rubric_version",
    "prompt_ref",
    "model_ref",
    "parser_version",
    "response_fingerprint",
)


def _find(evidence: EvidenceBundle, example_id: str, metric: str) -> JudgeEvidence | None:
    for item in evidence.judge_evidence:
        if item.example_id == example_id and item.metric == metric:
            return item
    return None


def _not_scored(
    name: str,
    status: ScoreStatus,
    code: str,
    message: str,
    carried: list[Diagnostic],
    *,
    validity: Validity = Validity.NOT_MEASURED,
    severity: Severity = Severity.ERROR,
    evidence_refs: list[str] | None = None,
) -> Score:
    diagnostic = Diagnostic(code=code, severity=severity, message=message)
    return Score(
        metric=name,
        value=None,
        status=status,
        validity=validity,
        evaluator_version=VERSION,
        diagnostics=[diagnostic, *carried],
        evidence_refs=evidence_refs or [],
    )


def _provenance(judged: JudgeEvidence) -> dict[str, Any]:
    return {
        key: getattr(judged, key) for key in _PROVENANCE_FIELDS if getattr(judged, key) is not None
    }


def evaluate(example: Example, context: EvaluatorContext, evidence: EvidenceBundle) -> Score:
    name = context.spec.name
    judged = _find(evidence, example.example_id, name)
    if judged is None:
        if "judge" in context.spec.required_evidence:
            # Required judge evidence absent: the gate cannot honestly run — block, never 0.0.
            return _not_scored(
                name,
                ScoreStatus.BLOCKED,
                "judge.evidence_missing",
                "required judge evidence was not collected for this example",
                [],
            )
        # judge_score on a metric that does not require judge evidence: nothing to score.
        return _not_scored(
            name,
            ScoreStatus.NON_EVALUABLE,
            "judge.evidence_absent",
            "no judge evidence to score and judge is not required for this metric",
            [],
            validity=Validity.NOT_APPLICABLE,
            severity=Severity.INFO,
        )
    carried = list(judged.diagnostics)
    # The evidence record was found, so every outcome below references it — a report can explain a
    # block or parser failure from the same-run evidence, not just a successful score.
    refs = [judged.evidence_id]
    if judged.status in _BLOCKING:
        return _not_scored(
            name,
            ScoreStatus.BLOCKED,
            f"judge.{judged.status.value}",
            f"judge evidence is not usable (status={judged.status.value})",
            carried,
            evidence_refs=refs,
        )
    # OK requires a usable value to score; MALFORMED / OK-without-value is a parser failure.
    if judged.status is not JudgeEvidenceStatus.OK or judged.parsed_value is None:
        return _not_scored(
            name,
            ScoreStatus.ERROR,
            "judge.unparseable",
            f"judge response could not be parsed into a score (status={judged.status.value})",
            carried,
            evidence_refs=refs,
        )
    score_range = context.spec.score_range
    if score_range is not None and not score_range[0] <= judged.parsed_value <= score_range[1]:
        return _not_scored(
            name,
            ScoreStatus.ERROR,
            "judge.value_out_of_range",
            f"judge value {judged.parsed_value} is outside the metric range {list(score_range)}",
            carried,
            evidence_refs=refs,
        )
    return Score(
        metric=name,
        value=judged.parsed_value,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version=VERSION,
        diagnostics=carried,
        evidence_refs=refs,
        provenance=_provenance(judged),
    )
