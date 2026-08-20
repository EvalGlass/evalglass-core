"""EG-P3-1 — pure diagnostic-cluster aggregation over a run's scores (effect-free, ordered)."""

from __future__ import annotations

from evalglass.core.clusters import DiagnosticCluster, cluster
from evalglass.core.contracts import Diagnostic, Severity
from evalglass.core.scores import Score, ScoreStatus, Validity


def _diag(code: str, severity: Severity = Severity.WARNING, message: str = "m") -> Diagnostic:
    return Diagnostic(code=code, severity=severity, message=message)


def _scored(metric: str, value: float, example_id: str, diags: list[Diagnostic]) -> Score:
    return Score(
        metric=metric,
        value=value,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="v@1",
        diagnostics=diags,
        example_id=example_id,
    )


def _blocked(metric: str, example_id: str, diags: list[Diagnostic]) -> Score:
    return Score(
        metric=metric,
        value=None,
        status=ScoreStatus.BLOCKED,
        validity=Validity.NOT_MEASURED,
        evaluator_version="v@1",
        diagnostics=diags,
        example_id=example_id,
    )


def test_two_scores_sharing_a_code_form_one_cluster() -> None:
    scores = [
        _scored("faithfulness", 0.0, "e1", [_diag("missing_citation")]),
        _scored("faithfulness", 0.0, "e2", [_diag("missing_citation")]),
    ]
    clusters = cluster(scores)
    assert len(clusters) == 1
    c = clusters[0]
    assert (c.metric, c.code, c.count) == ("faithfulness", "missing_citation", 2)


def test_distinct_codes_form_distinct_clusters() -> None:
    scores = [
        _scored("m", 0.0, "e1", [_diag("code_a")]),
        _scored("m", 0.0, "e2", [_diag("code_b")]),
    ]
    clusters = cluster(scores)
    assert {c.code for c in clusters} == {"code_a", "code_b"}
    assert all(c.count == 1 for c in clusters)


def test_order_invariant() -> None:
    scores = [
        _scored("m", 0.0, "e1", [_diag("a", Severity.ERROR)]),
        _scored("m", 0.0, "e2", [_diag("b", Severity.INFO)]),
        _scored("m", 0.0, "e3", [_diag("a", Severity.ERROR)]),
    ]
    assert cluster(scores) == cluster(list(reversed(scores)))


def test_blocked_item_is_grouped_never_zero() -> None:
    scores = [_blocked("m", "e1", [_diag("route_incomplete", Severity.ERROR)])]
    clusters = cluster(scores)
    assert len(clusters) == 1
    assert clusters[0].code == "route_incomplete"
    assert clusters[0].count == 1
    # A cluster carries a count + severity, never a fabricated 0.0 value for a non-scored item.
    assert not hasattr(clusters[0], "value")


def test_score_without_diagnostics_contributes_no_cluster() -> None:
    assert cluster([_scored("m", 1.0, "e1", [])]) == []


def test_severity_orders_clusters_most_severe_first() -> None:
    scores = [
        _scored("m", 0.0, "e1", [_diag("low", Severity.INFO)]),
        _scored("m", 0.0, "e2", [_diag("high", Severity.ERROR)]),
    ]
    clusters = cluster(scores)
    assert [c.code for c in clusters] == ["high", "low"]  # ERROR before INFO


def test_round_trip() -> None:
    scores = [_scored("m", 0.0, "e1", [_diag("c", Severity.ERROR, "boom")])]
    c = cluster(scores)[0]
    restored = DiagnosticCluster.from_dict(c.to_dict())
    assert restored == c


def test_a_score_counted_once_per_code_even_with_duplicate_diagnostics() -> None:
    scores = [_scored("m", 0.0, "e1", [_diag("c"), _diag("c", Severity.ERROR)])]
    clusters = cluster(scores)
    assert len(clusters) == 1
    assert clusters[0].count == 1  # one item, not two
    assert clusters[0].severity is Severity.ERROR  # representative = max severity for the code
