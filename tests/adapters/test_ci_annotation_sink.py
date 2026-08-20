"""CI annotation sink — GitHub workflow commands rendered from the Scorecard (EG-M2-3).

The CI sink is a :class:`~evalglass.harness.ports.ScoreSink`: it renders immutable Scorecard
data as GitHub workflow annotations and never recomputes the verdict or authority. Every verdict
word is sourced from the :class:`~evalglass.core.Verdict` enum (no string literals — the M1
scan-gate lesson), so the annotations can never headline a verdict the Scorecard does not hold.
A failing/blocked gate becomes an ``::error``; an informational/pass run never emits one.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.adapters.ci_annotation_sink import CiAnnotationSink
from evalglass.core import (
    AggregatedMetric,
    Aggregation,
    Diagnostic,
    RunRecord,
    Scorecard,
    Severity,
    Verdict,
    VerdictPayload,
)
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.ports import ScoreSink
from evalglass.harness.runner import run_config


def _metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": "d.jsonl",
    }
    base.update(over)
    return base


def _record(tmp_path: Path, *, mode: str) -> RunRecord:
    """Build a real Scorecard through the runner for each verdict mode."""
    output = "5" if mode == "fail" else "4"  # mismatch → failing gate
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": output, "reference": "4"}) + "\n", encoding="utf-8"
    )
    policy = "forbidden" if mode == "blocked" else "permitted"
    gating = mode in {"pass", "fail", "blocked"}
    metric = (
        _metric(metric_status="gating", threshold_approval="approved", threshold=0.5)
        if gating
        else _metric()
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": policy}],
            "metrics": [metric],
        }
    )
    return run_config(cfg, root=tmp_path)


def test_sink_satisfies_protocol() -> None:
    assert isinstance(CiAnnotationSink(), ScoreSink)


def test_informational_emits_notice_no_error(tmp_path: Path) -> None:
    out = CiAnnotationSink().render(_record(tmp_path, mode="informational").scorecard)
    assert "::notice" in out
    assert "::error" not in out  # no active gate → nothing failed
    assert f"verdict={Verdict.INFORMATIONAL.value}" in out


def test_pass_emits_no_error(tmp_path: Path) -> None:
    out = CiAnnotationSink().render(_record(tmp_path, mode="pass").scorecard)
    assert f"verdict={Verdict.PASS.value}" in out
    assert "::error" not in out


def test_failing_gate_emits_error_citing_metric_and_value(tmp_path: Path) -> None:
    record = _record(tmp_path, mode="fail")
    out = CiAnnotationSink().render(record.scorecard)
    assert f"verdict={Verdict.FAIL.value}" in out
    assert "::error" in out
    # cites the failing metric, its measured value, and the verdict reason (from the Scorecard)
    assert "exact_match" in out
    assert "below_threshold" in out


def test_blocked_gate_emits_error_with_reason(tmp_path: Path) -> None:
    record = _record(tmp_path, mode="blocked")
    out = CiAnnotationSink().render(record.scorecard)
    assert f"verdict={Verdict.BLOCKED.value}" in out
    assert "::error" in out
    assert "exact_match" in out
    # a forbidden-policy block surfaces its authority reason
    assert "policy_forbidden" in out


def test_no_overclaim_only_the_scorecard_verdict_headlines(tmp_path: Path) -> None:
    # The summary must headline exactly the Scorecard's verdict — never another verdict word.
    record = _record(tmp_path, mode="informational")
    out = CiAnnotationSink().render(record.scorecard)
    actual = record.scorecard.verdict.verdict
    for verdict in Verdict:
        present = f"verdict={verdict.value}" in out
        assert present == (verdict is actual), f"overclaim: {verdict.value} in CI output"


def test_control_chars_are_escaped_no_command_injection() -> None:
    # A diagnostic message / metric name carrying workflow-command control characters
    # (newline, ::, %) must not split the output into an extra command. GitHub escaping
    # (%0A / %0D / %25, and %3A/%2C in property values) keeps each annotation one line.
    payload = VerdictPayload(Verdict.INFORMATIONAL, ci_should_fail=False, informational_metrics=[])
    sc = Scorecard(
        verdict=payload,
        metrics=[
            AggregatedMetric(
                metric="m\n::error::injected-via-metric",
                aggregation=Aggregation.MEAN,
                value=None,
                included_count=0,
            )
        ],
        authority={},
        diagnostics=[
            Diagnostic(
                code="weird,code",
                severity=Severity.WARNING,
                message="line one\n::error::injected-via-diagnostic",
            )
        ],
    )
    out = CiAnnotationSink().render(sc)
    # Exactly the three intended commands (summary + metric notice + diagnostic warning):
    command_lines = [ln for ln in out.splitlines() if ln.startswith("::")]
    assert len(command_lines) == 3
    # The injected payloads never appear as standalone commands.
    assert "\n::error::injected-via-metric" not in out
    assert "\n::error::injected-via-diagnostic" not in out
    # Newlines are percent-encoded instead.
    assert "%0A" in out


def test_render_does_not_mutate_or_recompute(tmp_path: Path) -> None:
    # The sink consumes the immutable Scorecard; rendering twice is identical and the
    # verdict word always equals the product's, never a recomputation.
    sc = _record(tmp_path, mode="fail").scorecard
    first = CiAnnotationSink().render(sc)
    second = CiAnnotationSink().render(sc)
    assert first == second
    assert f"verdict={sc.verdict.verdict.value}" in first
