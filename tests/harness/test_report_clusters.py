"""EG-P3-3 — renderers show failure clusters from typed data only (no re-grouping)."""

from __future__ import annotations

from evalglass.core.aggregation import AggregatedMetric
from evalglass.core.clusters import DiagnosticCluster
from evalglass.core.contracts import Severity
from evalglass.core.registry import Aggregation
from evalglass.core.results import Scorecard
from evalglass.core.verdict import decide_verdict
from evalglass.harness.report import MarkdownScoreSink
from evalglass.harness.report_html_legacy import HtmlScoreSink


def _scorecard(clusters: list[DiagnosticCluster]) -> Scorecard:
    agg = AggregatedMetric(
        metric="faithfulness", aggregation=Aggregation.MEAN, value=0.5, included_count=2
    )
    return Scorecard(verdict=decide_verdict([]), metrics=[agg], authority={}, clusters=clusters)


_CLUSTER = DiagnosticCluster(
    metric="faithfulness",
    code="missing_citation",
    severity=Severity.WARNING,
    count=2,
    message="no supporting citation found",
)


def test_markdown_renders_cluster_subrow() -> None:
    md = MarkdownScoreSink().render(_scorecard([_CLUSTER]))
    assert "Failure clusters" in md
    assert "missing_citation" in md
    assert "2 cases" in md


def test_markdown_without_clusters_is_unchanged() -> None:
    md = MarkdownScoreSink().render(_scorecard([]))
    assert "Failure clusters" not in md  # no empty cluster block (byte-identical to pre-P3)


def test_html_renders_cluster_subrow() -> None:
    html = HtmlScoreSink().render(_scorecard([_CLUSTER]))
    assert "missing_citation" in html
    assert "2 cases" in html
    assert "cluster" in html  # a cluster sub-row/class is present


def test_html_without_clusters_has_no_cluster_markup() -> None:
    html = HtmlScoreSink().render(_scorecard([]))
    assert '<div class="cluster' not in html  # no cluster sub-row (the CSS class may still exist)


def test_singular_case_wording() -> None:
    one = DiagnosticCluster(
        metric="faithfulness",
        code="route_incomplete",
        severity=Severity.ERROR,
        count=1,
        message="x",
    )
    md = MarkdownScoreSink().render(_scorecard([one]))
    assert "1 case " in md or "1 case —" in md  # singular, not "1 cases"
