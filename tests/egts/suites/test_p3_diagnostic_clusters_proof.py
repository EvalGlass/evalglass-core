"""EGTS-P3 — diagnostic clusters over a real runrecord (EG-P3-4; ADR 0047).

Proves, through the **real** harness (`run_config` → typed `RunRecord`/`Scorecard`), that a run
whose items fail the same way surfaces a diagnostic **cluster** keyed by `Diagnostic.code`: the
typed `Scorecard.clusters` groups the failing items, the persisted `runrecord.json` survives the
anti-tamper recompute, and the renderers echo it. The cluster axis is **diagnostic-cause** — not
per-source-function (ADR 0037), a different axis from the explorer's call-identity grouping.
Every negative control (tests/CLAUDE.md §12) proves the checker is sensitive.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import RunRecord, ScoreStatus, Verdict, cluster
from evalglass.core._validation import ContractError
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.dashboard import DashboardMeta, project_run
from evalglass.harness.report import MarkdownScoreSink
from evalglass.harness.report_html import render_dashboard
from evalglass.harness.runner import run_config

# A host evaluator: outputs that are not "good" are non_evaluable and carry a shared diagnostic
# code — so several failing items form one cluster, and no non-scored item becomes a 0.0.
_PROBE = """
from evalglass.core import Diagnostic, Score, ScoreStatus, Severity, Validity


def evaluate(example, context, evidence):
    if example.output == "good":
        return Score(metric=context.spec.name, value=1.0, status=ScoreStatus.SCORED,
                     validity=Validity.VALID, evaluator_version="probe@1")
    return Score(
        metric=context.spec.name, value=None, status=ScoreStatus.NON_EVALUABLE,
        validity=Validity.NOT_APPLICABLE, evaluator_version="probe@1",
        diagnostics=[Diagnostic(code="bad_output", severity=Severity.WARNING,
                                message="output is not well-formed")],
    )
"""


def _metric() -> dict[str, object]:
    return {
        "name": "wellformed",
        "evaluator_ref": "evaluators/probe.py:evaluate",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0, 1],
    }


def _run(tmp_path: Path, outputs: list[str]) -> RunRecord:
    (tmp_path / "evaluators").mkdir(exist_ok=True)
    (tmp_path / "evaluators" / "probe.py").write_text(_PROBE, encoding="utf-8")
    lines = [
        json.dumps({"trace_id": f"t{i}", "behavior": {"output": o}}) for i, o in enumerate(outputs)
    ]
    (tmp_path / "t.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfg = RuntimeConfig.from_mapping({"traces": [{"path": "t.jsonl"}], "metrics": [_metric()]})
    return run_config(cfg, root=tmp_path)


def test_p3_failing_items_form_a_cluster(tmp_path: Path) -> None:
    """p3.clusters.real_runrecord — several items failing the same way form one typed cluster."""
    record = _run(tmp_path, ["good", "bad1", "bad2"])
    # Typed artifacts first: exactly one cluster, keyed by the shared diagnostic code, count 2.
    assert len(record.scorecard.clusters) == 1
    c = record.scorecard.clusters[0]
    assert (c.metric, c.code, c.count) == ("wellformed", "bad_output", 2)
    # The failing items are non_evaluable (grouped by cause), never a fabricated 0.0.
    bad = [s for s in record.scores if s.status is ScoreStatus.NON_EVALUABLE]
    assert len(bad) == 2
    assert all(s.value is None for s in bad)
    # The run is honestly informational — a cluster view changes no verdict.
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL
    # The persisted runrecord survives the anti-tamper recompute (clusters derive from scores).
    reloaded = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert reloaded.scorecard.clusters == record.scorecard.clusters


def test_p3_renderers_echo_the_cluster(tmp_path: Path) -> None:
    record = _run(tmp_path, ["good", "bad1", "bad2"])
    md = MarkdownScoreSink().render(record.scorecard)
    assert "bad_output" in md
    assert "2 cases" in md
    # The diagnostic-first dashboard echoes the cluster through its typed projection (never a
    # re-grouping): the per-metric diagnostics carry the cluster's code + count, and the embedded
    # projection JSON in the self-contained HTML carries them verbatim.
    projection = project_run(
        record.scorecard, record, config=None, meta=DashboardMeta(run_id=record.run_id)
    )
    diagnostics = [d for metric in projection["metrics"] for d in metric["diagnostics"]]
    assert any(d["code"] == "bad_output" and d["count"] == 2 for d in diagnostics)
    html = render_dashboard(projection)
    assert "bad_output" in html


def test_negctl_order_invariance(tmp_path: Path) -> None:
    """Negative control: the same scores in a different order give equal clusters."""
    record = _run(tmp_path, ["good", "bad1", "bad2"])
    assert cluster(record.scores) == cluster(list(reversed(record.scores)))


def test_negctl_clean_run_has_no_clusters(tmp_path: Path) -> None:
    """Negative control: a run with no diagnostics fabricates no cluster (field absent in JSON)."""
    record = _run(tmp_path, ["good", "good"])
    assert record.scorecard.clusters == []
    assert "clusters" not in record.to_dict()["scorecard"]


def test_negctl_tampered_cluster_fails_closed(tmp_path: Path) -> None:
    """Negative control: a hand-edited stored cluster count fails the anti-tamper recompute."""
    record = _run(tmp_path, ["good", "bad1", "bad2"])
    d = record.to_dict()
    d["scorecard"]["clusters"][0]["count"] = 99
    try:
        RunRecord.from_dict(d)
    except ContractError:
        return
    raise AssertionError("a tampered cluster must fail closed on load")
