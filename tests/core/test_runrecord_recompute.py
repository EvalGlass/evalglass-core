"""Load-time recomputation: a tampered RunRecord cannot parse (M7 T5, G5).

The audit's P1-4: a passing scorecard's aggregate was changed 1.0 -> 0.0 while three
raw scores stayed 1.0, and the edited record still parsed. teta recomputes aggregates
and estimate points from the raw scores on load and fails closed on any mismatch.

See src/evalglass/core/results.py and docs/TETA_REDESIGN.md G5/N5.
"""

from __future__ import annotations

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.aggregation import aggregate
from evalglass.core.contracts import UnitKind
from evalglass.core.estimate import estimate
from evalglass.core.registry import Aggregation, Direction, Lens, MetricSpec, ScoreType
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.core.verdict import decide_verdict


def _spec() -> MetricSpec:
    return MetricSpec(
        name="exact_match",
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="exact_match@1",
        aggregation=Aggregation.RATE,
    )


def _scored(v: float) -> Score:
    return Score("exact_match", v, ScoreStatus.SCORED, Validity.VALID, "1")


def _record(scores: list[Score]) -> RunRecord:
    spec = _spec()
    agg = aggregate(spec.name, scores, spec.aggregation)
    est = estimate(spec, scores)
    verdict = decide_verdict([])  # no active gate -> informational
    from evalglass.core.clusters import cluster

    sc = Scorecard(
        verdict=verdict, metrics=[agg], authority={}, estimates=[est], clusters=cluster(scores)
    )
    dims = {
        d: {"x": 1}
        for d in [
            "framework",
            "metric_spec",
            "evaluator",
            "dataset",
            "example",
            "evidence",
            "config",
            "policy",
            "authority",
            "baseline",
        ]
    }
    from evalglass.core.provenance import RunFingerprint

    return RunRecord(run_id="r1", scorecard=sc, scores=scores, provenance=RunFingerprint.of(dims))


def test_consistent_record_round_trips() -> None:
    rec = _record([_scored(1.0), _scored(1.0), _scored(0.0)])
    again = RunRecord.from_dict(rec.to_dict())
    assert again.scorecard.metrics[0].value == rec.scorecard.metrics[0].value


def test_tampered_aggregate_fails_to_load() -> None:
    # The exact audit tamper: raw scores all 1.0, but the stored aggregate flipped to 0.0.
    rec = _record([_scored(1.0), _scored(1.0), _scored(1.0)])
    d = rec.to_dict()
    assert d["scorecard"]["metrics"][0]["value"] == 1.0
    d["scorecard"]["metrics"][0]["value"] = 0.0
    with pytest.raises(ContractError, match="contradicts the raw scores"):
        RunRecord.from_dict(d)


def test_tampered_included_count_fails_to_load() -> None:
    rec = _record([_scored(1.0), _scored(1.0), _scored(1.0)])
    d = rec.to_dict()
    d["scorecard"]["metrics"][0]["included_count"] = 99
    with pytest.raises(ContractError):
        RunRecord.from_dict(d)


def test_tampered_estimate_point_fails_to_load() -> None:
    rec = _record([_scored(1.0), _scored(1.0), _scored(1.0)])
    d = rec.to_dict()
    # move only the estimate point, leaving the aggregate consistent
    d["scorecard"]["estimates"][0]["point"] = 0.0
    with pytest.raises(ContractError):
        RunRecord.from_dict(d)


def test_tampered_estimate_n_effective_fails_to_load() -> None:
    rec = _record([_scored(1.0), _scored(0.0)])
    d = rec.to_dict()
    d["scorecard"]["estimates"][0]["n_effective"] = 7
    with pytest.raises(ContractError):
        RunRecord.from_dict(d)


# --- EG-P3-2: diagnostic clusters are additive + recompute-safe ---------------


def _scored_diag(v: float, code: str, example_id: str) -> Score:
    from evalglass.core.contracts import Diagnostic, Severity

    return Score(
        "exact_match",
        v,
        ScoreStatus.SCORED,
        Validity.VALID,
        "1",
        diagnostics=[Diagnostic(code=code, severity=Severity.WARNING, message="m")],
        example_id=example_id,
    )


def test_clean_run_emits_no_clusters_field_byte_identical() -> None:
    # EG-P3-2: scores with no diagnostics ⇒ no clusters key (pre-P3 scorecard byte-identical).
    d = _record([_scored(1.0), _scored(0.0)]).to_dict()
    assert "clusters" not in d["scorecard"]


def test_record_with_clusters_round_trips() -> None:
    rec = _record(
        [_scored_diag(0.0, "missing_citation", "e1"), _scored_diag(0.0, "missing_citation", "e2")]
    )
    d = rec.to_dict()
    assert d["scorecard"]["clusters"][0]["code"] == "missing_citation"
    assert d["scorecard"]["clusters"][0]["count"] == 2
    again = RunRecord.from_dict(d)
    assert again.scorecard.clusters == rec.scorecard.clusters


def test_tampered_cluster_count_fails_to_load() -> None:
    # The anti-tamper guarantee extends to clusters: a stored cluster must match the raw scores.
    rec = _record(
        [_scored_diag(0.0, "missing_citation", "e1"), _scored_diag(0.0, "missing_citation", "e2")]
    )
    d = rec.to_dict()
    assert d["scorecard"]["clusters"][0]["count"] == 2
    d["scorecard"]["clusters"][0]["count"] = 99
    with pytest.raises(ContractError):
        RunRecord.from_dict(d)


def test_fabricated_cluster_fails_to_load() -> None:
    # Injecting a cluster that the raw scores do not support must fail closed.
    rec = _record([_scored(1.0), _scored(1.0)])  # clean run, no clusters
    d = rec.to_dict()
    d["scorecard"]["clusters"] = [
        {
            "metric": "exact_match",
            "code": "made_up",
            "severity": "error",
            "count": 5,
            "message": "x",
        }
    ]
    with pytest.raises(ContractError):
        RunRecord.from_dict(d)
