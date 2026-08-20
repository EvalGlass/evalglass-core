"""Built-in judge_score evaluator — parse judge evidence into a Score (EG-M4-4).

The harness collects judge evidence (an effect); this **effect-free** built-in turns it
into a ``Score``. The cardinal rule (CLAUDE.md §9): a missing / timed-out / errored /
unparseable judge response is **never** a ``0.0`` — only a usable value is ``scored``,
everything else is ``blocked``/``error`` with typed diagnostics and no value.
"""

from __future__ import annotations

import pytest

from evalglass.core import (
    EvaluatorContext,
    EvalUnit,
    EvidenceBundle,
    Example,
    JudgeEvidence,
    JudgeEvidenceStatus,
    MetricSpec,
    Score,
    ScoreStatus,
    UnitKind,
    Validity,
)
from evalglass.core.builtins import BUILTINS
from evalglass.core.builtins.judge_score import VERSION, evaluate


def _spec(score_range: tuple[float, float] = (0.0, 1.0)) -> MetricSpec:
    return MetricSpec.from_dict(
        {
            "name": "faithfulness",
            "version": "1",
            "lens": "non_reference",
            "granularity": "call",
            "score_type": "continuous",
            "direction": "higher_is_better",
            "evaluator_ref": VERSION,
            "score_range": list(score_range),
            "required_evidence": ["judge"],
        }
    )


def _example() -> Example:
    return Example(
        example_id="e1",
        input="q",
        output="a",
        unit=EvalUnit(unit_id="e1", kind=UnitKind.CALL, trace_id="t"),
    )


def _bundle(*judge: JudgeEvidence) -> EvidenceBundle:
    return EvidenceBundle(judge_evidence=list(judge))


def _judge(status: JudgeEvidenceStatus, **kw: object) -> JudgeEvidence:
    return JudgeEvidence(example_id="e1", metric="faithfulness", status=status, **kw)  # type: ignore[arg-type]


def _run(evidence: EvidenceBundle, score_range: tuple[float, float] = (0.0, 1.0)) -> Score:
    return evaluate(_example(), EvaluatorContext(spec=_spec(score_range), params={}), evidence)


# --- a usable judge response is scored --------------------------------------


def test_ok_with_value_is_scored() -> None:
    score = _run(_bundle(_judge(JudgeEvidenceStatus.OK, parsed_value=0.75, rubric_ref="r.md")))
    assert score.status is ScoreStatus.SCORED
    assert score.validity is Validity.VALID
    assert score.value == pytest.approx(0.75)
    assert score.evidence_refs  # points back at the judge evidence
    assert score.provenance.get("rubric_ref") == "r.md"


def test_value_out_of_range_is_error_not_clamped() -> None:
    score = _run(_bundle(_judge(JudgeEvidenceStatus.OK, parsed_value=1.5)))
    assert score.status is ScoreStatus.ERROR
    assert score.value is None


# --- failures never become a low score --------------------------------------


def test_missing_evidence_blocks() -> None:
    score = _run(_bundle())  # no judge evidence collected for this example/metric
    assert score.status is ScoreStatus.BLOCKED
    assert score.value is None
    assert score.diagnostics


@pytest.mark.parametrize(
    "status",
    [JudgeEvidenceStatus.MISSING, JudgeEvidenceStatus.TIMEOUT, JudgeEvidenceStatus.PROVIDER_ERROR],
)
def test_unusable_response_blocks(status: JudgeEvidenceStatus) -> None:
    score = _run(_bundle(_judge(status)))
    assert score.status is ScoreStatus.BLOCKED
    assert score.value is None


def test_malformed_response_is_error() -> None:
    score = _run(_bundle(_judge(JudgeEvidenceStatus.MALFORMED, raw_response="not json")))
    assert score.status is ScoreStatus.ERROR
    assert score.value is None


def test_ok_without_value_is_error() -> None:
    # an "OK" status with no parsed value is unparseable evidence, not a 0.0
    score = _run(_bundle(_judge(JudgeEvidenceStatus.OK)))
    assert score.status is ScoreStatus.ERROR
    assert score.value is None


def test_diagnostics_are_carried_through() -> None:
    from evalglass.core import Diagnostic, Severity

    diag = Diagnostic(code="judge_timeout", severity=Severity.ERROR, message="timed out")
    score = _run(_bundle(_judge(JudgeEvidenceStatus.TIMEOUT, diagnostics=[diag])))
    assert any(d.code == "judge_timeout" for d in score.diagnostics)


def test_evidence_for_a_different_metric_is_ignored() -> None:
    other = JudgeEvidence(
        example_id="e1", metric="relevance", status=JudgeEvidenceStatus.OK, parsed_value=0.9
    )
    score = _run(_bundle(other))  # no evidence for "faithfulness"
    assert score.status is ScoreStatus.BLOCKED


def test_optional_missing_evidence_is_non_evaluable() -> None:
    # a metric that does NOT require judge evidence is non_evaluable (not blocked) when absent
    spec = MetricSpec.from_dict(
        {
            "name": "faithfulness",
            "version": "1",
            "lens": "non_reference",
            "granularity": "call",
            "score_type": "continuous",
            "direction": "higher_is_better",
            "evaluator_ref": VERSION,
            "score_range": [0.0, 1.0],
        }
    )
    score = evaluate(_example(), EvaluatorContext(spec=spec, params={}), _bundle())
    assert score.status is ScoreStatus.NON_EVALUABLE
    assert score.validity is Validity.NOT_APPLICABLE


# --- registry ---------------------------------------------------------------


def test_registered_as_a_builtin() -> None:
    assert BUILTINS[VERSION] is evaluate
