"""EGTS-M4 — Judge Proof: fake-judge route, rubric provenance, calibration authority, scorecard.

Drives the **real** judge surfaces — the harness ``run_config`` end-to-end (fake judge →
``JudgeEvidence`` → the effect-free ``judge_score`` evaluator → calibration authority → the
single Verdict Engine) and ``collect_judge_evidence`` — against deterministic fixtures,
checking the typed ``Scorecard``/``RunRecord`` and proving each checker fails for the right
reason (negative controls). The required tier is hermetic: fake evidence only, no provider SDK.

- **EGTS-M4-1** fake-judge route scores; required tier imports no provider SDK; ledger proves
  policy-aware no-call.
- **EGTS-M4-2** a rubric change breaks baseline comparability; a malformed response is `error`,
  never a `0.0`.
- **EGTS-M4-3** calibrated+approved gates (PASS); drifted blocks; uncalibrated is informational;
  the yaml cannot self-declare calibration without a host record.
- **EGTS-M4-4** judge scores behave like normal metrics; the report states the verdict, no more.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

import evalglass
from evalglass.adapters.judge_fake import FakeJudgeModel
from evalglass.core import (
    BaselineState,
    ComparableRunFingerprint,
    EvalUnit,
    Example,
    RunRecord,
    ScoreStatus,
    UnitKind,
    Verdict,
)
from evalglass.harness.config import MetricConfig, RuntimeConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.judge import collect_judge_evidence
from evalglass.harness.report import MarkdownScoreSink
from evalglass.harness.runner import run_config
from tests.egts.checkers import (
    CheckerError,
    check_authority,
    check_exit_class,
    check_judge_ledger,
    check_no_provider_sdk,
    check_report_no_overclaim,
    check_verdict,
)

_SRC = Path(evalglass.__file__).resolve().parent
_CAL = {"status": "calibrated", "approver": "alice", "rationale": "50 labels", "variance_runs": 5}
_THRESH = {
    "value": 0.5,
    "direction": "higher_is_better",
    "variance": 0.05,
    "approver": "alice",
    "rationale": "p95",
    "version": "1",
}


def _cfg(
    tmp_path: Path,
    *,
    calibration: dict[str, Any] | None = None,
    rubric_version: str | None = None,
    rubric_body: str = "# rubric\n",
    default_value: float | None = 0.8,
    judge_mode: str | None = None,
    metric_status: str = "gating",
    required_evidence: tuple[str, ...] = ("judge",),
    example_id: str = "e1",
    yaml_calibrated: bool = False,
    measurement: bool = False,
) -> RuntimeConfig:
    record: dict[str, Any] = {
        "example_id": example_id,
        "input": "q",
        "output": "a",
        "reference": "a",
    }
    if judge_mode is not None:
        record["context"] = {"judge": {"mode": judge_mode}}
    (tmp_path / "d.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    metric: dict[str, Any] = {
        "name": "faithfulness",
        "evaluator_ref": "judge_score@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0.0, 1.0],
        "required_evidence": list(required_evidence),
        "metric_status": metric_status,
    }
    if yaml_calibrated:  # the bypass attempt: declare authority in the yaml, not a record
        metric.update(
            {"judge_calibration": "calibrated", "threshold_approval": "approved", "threshold": 0.5}
        )
    if calibration is not None:
        (tmp_path / "calibration").mkdir(exist_ok=True)
        (tmp_path / "calibration" / "faithfulness.json").write_text(
            json.dumps(calibration), encoding="utf-8"
        )
        metric["calibration"] = "calibration/faithfulness.json"
    if rubric_version is not None:
        (tmp_path / "rubrics").mkdir(exist_ok=True)
        (tmp_path / "rubrics" / "f.md").write_text(rubric_body, encoding="utf-8")
        metric["rubric"] = {"path": "rubrics/f.md", "version": rubric_version}
    # A judge can gate only if it is a real MEASUREMENT instrument (EG-NR-1). The default fake
    # adapter is a SYNTHETIC_TEST_DOUBLE and stays informational regardless of calibration; the
    # authorized-gate proofs use a hermetic command judge (a host subprocess) whose capability the
    # harness reads from the adapter. ``default_value=None`` makes it emit no value → an evidence
    # failure that blocks a gating metric.
    if measurement:
        (tmp_path / "judges").mkdir(exist_ok=True)
        if default_value is None:
            body = "import sys, json\njson.load(sys.stdin)\nprint('{}')\n"
        else:
            body = (
                "import sys, json\njson.load(sys.stdin)\n"
                f"print(json.dumps({{'value': {default_value}, 'rationale': 'ok'}}))\n"
            )
        (tmp_path / "judges" / "j.py").write_text(body, encoding="utf-8")
        judge_block: dict[str, Any] = {
            "adapter": "command",
            "command": [sys.executable, "judges/j.py"],
        }
    else:
        judge_block = {"adapter": "fake", "default_value": default_value}
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": judge_block,
        "metrics": [metric],
    }
    return RuntimeConfig.from_mapping(raw)


def _score_status(record: RunRecord, metric: str) -> ScoreStatus:
    return next(s.status for s in record.scores if s.metric == metric)


# === EGTS-M4-1 — fake-judge route + no-network/no-SDK + ledger ==============


def test_fake_judge_route_produces_a_score(tmp_path: Path) -> None:
    record = run_config(_cfg(tmp_path, metric_status="informational"), tmp_path)
    assert _score_status(record, "faithfulness") is ScoreStatus.SCORED


def test_required_tier_imports_no_provider_sdk() -> None:
    # The opt-in egress lanes (live-judge, openai-judge, hosted-dashboard sink) use stdlib
    # ``urllib`` behind an injected transport — never a provider SDK — so they are the only
    # allow-listed network clients.
    check_no_provider_sdk(
        _SRC,
        ["core", "harness", "adapters"],
        allow=[
            "adapters/judge_live.py",
            "adapters/judge_openai.py",
            "adapters/score_sink_dashboard.py",
        ],
    )


def test_no_sdk_checker_detects_a_provider_import(tmp_path: Path) -> None:
    """Negative control: a module importing a provider SDK fails the hermetic-tier checker."""
    pkg = tmp_path / "fakecore"
    pkg.mkdir()
    (pkg / "leak.py").write_text("import openai\n", encoding="utf-8")
    with pytest.raises(CheckerError):
        check_no_provider_sdk(tmp_path, ["fakecore"])


def _ex(example_id: str, **ctx: Any) -> Example:
    return Example(
        example_id=example_id,
        input="q",
        output="a",
        unit=EvalUnit(unit_id=example_id, kind=UnitKind.CALL, trace_id="t"),
        context=ctx,
    )


def test_judge_ledger_skips_forbidden_egress() -> None:
    judge = FakeJudgeModel(default_value=0.7)
    metric = MetricConfig.from_mapping(
        {
            "name": "faithfulness",
            "evaluator_ref": "judge_score@1",
            "lens": "non_reference",
            "score_type": "continuous",
            "score_range": [0.0, 1.0],
            "required_evidence": ["judge"],
        },
        0,
    )
    examples = [(_ex("permitted"), True), (_ex("forbidden"), False)]
    from evalglass.harness.plan import MetricView, build_plan

    view = MetricView(
        name=metric.spec.name,
        selector=metric.selector,
        is_judge="judge" in metric.spec.required_evidence,
        is_reference=metric.spec.lens.value == "reference",
        prerequisites=list(metric.spec.required_evidence),
    )
    plan = build_plan(run_id="t", subjects_in=examples, metrics=[view])
    example_by_subject = {f"s{i}": ex for i, (ex, _eg) in enumerate(examples)}
    collect_judge_evidence(judge, plan, example_by_subject)
    check_judge_ledger(judge.ledger, expected=[("permitted", "faithfulness")])


def test_judge_ledger_checker_detects_a_missing_call() -> None:
    """Negative control: declaring an expectation that omits a real call fails the ledger check."""
    with pytest.raises(CheckerError):
        check_judge_ledger([("permitted", "faithfulness")], expected=[])


# === EGTS-M4-2 — rubric provenance + parser diagnostics =====================


def test_rubric_version_change_breaks_comparability(tmp_path: Path) -> None:
    base = run_config(_cfg(tmp_path, rubric_version="1"), tmp_path).provenance
    changed = run_config(_cfg(tmp_path, rubric_version="2"), tmp_path).provenance
    state = ComparableRunFingerprint(current=changed, baseline=base, requested=True).state
    assert state is BaselineState.NOT_COMPARABLE


def test_unrelated_change_stays_comparable(tmp_path: Path) -> None:
    """Specificity: an example-only change (a non-gating dimension) stays comparable."""
    base = run_config(_cfg(tmp_path, rubric_version="1", example_id="e1"), tmp_path).provenance
    other = run_config(_cfg(tmp_path, rubric_version="1", example_id="e2"), tmp_path).provenance
    state = ComparableRunFingerprint(current=other, baseline=base, requested=True).state
    assert state is BaselineState.COMPARABLE


def test_malformed_judge_response_is_error_not_zero(tmp_path: Path) -> None:
    record = run_config(
        _cfg(tmp_path, metric_status="informational", judge_mode="malformed"), tmp_path
    )
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is ScoreStatus.ERROR
    assert score.value is None  # a malformed judge is never a 0.0


# === EGTS-M4-3 — calibration / threshold / drift authority ==================


def test_calibrated_approved_judge_gates_and_passes(tmp_path: Path) -> None:
    sc = run_config(
        _cfg(tmp_path, calibration={"calibration": _CAL, "threshold": _THRESH}, measurement=True),
        tmp_path,
    ).scorecard
    check_verdict(sc, expected=Verdict.PASS)  # measurement judge 0.8 >= approved 0.5
    check_authority(sc, "faithfulness", expected_level="gating", expected_blocked=False)
    check_exit_class(sc, expected="zero")


def test_fake_judge_cannot_gate_even_when_calibrated(tmp_path: Path) -> None:
    """Negative control (EG-NR-1): a synthetic (fake) judge stays informational even with a
    complete calibration record + approved threshold — capability precedes calibration."""
    sc = run_config(
        _cfg(tmp_path, calibration={"calibration": _CAL, "threshold": _THRESH}, measurement=False),
        tmp_path,
    ).scorecard
    check_verdict(sc, expected=Verdict.INFORMATIONAL)
    check_authority(sc, "faithfulness", expected_level="informational")
    assert "judge_fake_non_authoritative" in sc.authority["faithfulness"].reasons


def test_drifted_judge_blocks(tmp_path: Path) -> None:
    drifted = {"calibration": {**_CAL, "status": "drifted"}, "threshold": _THRESH}
    sc = run_config(_cfg(tmp_path, calibration=drifted, measurement=True), tmp_path).scorecard
    check_verdict(sc, expected=Verdict.BLOCKED)
    check_authority(sc, "faithfulness", expected_level="gating", expected_blocked=True)
    check_exit_class(sc, expected="nonzero_blocked")


def test_uncalibrated_judge_is_informational(tmp_path: Path) -> None:
    sc = run_config(_cfg(tmp_path), tmp_path).scorecard  # no calibration file
    check_verdict(sc, expected=Verdict.INFORMATIONAL)
    check_authority(sc, "faithfulness", expected_level="informational")


def test_yaml_cannot_self_declare_calibration(tmp_path: Path) -> None:
    """Negative control: yaml-declared calibrated/approved without a record cannot gate."""
    sc = run_config(_cfg(tmp_path, yaml_calibrated=True), tmp_path).scorecard
    check_authority(sc, "faithfulness", expected_level="informational")


def test_incomplete_approved_threshold_is_a_setup_error(tmp_path: Path) -> None:
    bad = {"calibration": _CAL, "threshold": {"value": 0.5, "direction": "higher_is_better"}}
    cfg = _cfg(tmp_path, calibration=bad)
    with pytest.raises(SetupError):
        run_config(cfg, tmp_path)


# === EGTS-M4-4 — judge scorecard / report ===================================


def test_missing_judge_evidence_blocks(tmp_path: Path) -> None:
    # a calibrated MEASUREMENT judge that emits no value -> an evidence failure that blocks the
    # otherwise-authorized gate (evidence problem != a low quality score).
    sc = run_config(
        _cfg(
            tmp_path,
            calibration={"calibration": _CAL, "threshold": _THRESH},
            default_value=None,
            measurement=True,
        ),
        tmp_path,
    ).scorecard
    check_verdict(sc, expected=Verdict.BLOCKED)


def test_judge_report_states_the_verdict_no_overclaim(tmp_path: Path) -> None:
    sc = run_config(
        _cfg(tmp_path, calibration={"calibration": _CAL, "threshold": _THRESH}), tmp_path
    ).scorecard
    report = MarkdownScoreSink().render(sc)
    check_report_no_overclaim(report, sc)


def test_report_overclaim_checker_detects_a_mutation(tmp_path: Path) -> None:
    """Negative control: a report headlining a stronger verdict than the Scorecard fails."""
    sc = run_config(_cfg(tmp_path), tmp_path).scorecard  # informational
    mutated = MarkdownScoreSink().render(sc) + "\n**Verdict:** pass\n"
    with pytest.raises(CheckerError):
        check_report_no_overclaim(mutated, sc)
