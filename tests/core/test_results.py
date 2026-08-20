"""RunRecord + Scorecard output contracts (EG-M0-6a).

These are the primary machine artifacts (``CLAUDE.md §4`` non-negotiable #6):
the Scorecard is the authority-aware run summary (verdict, per-metric aggregates,
per-metric authority, baseline state, diagnostics); the RunRecord is the complete
record (scorecard + every individual score + provenance + comparability). Both
round-trip through plain JSON and fail closed on malformed input; they compose the
already-built contracts rather than redefining their meaning.
"""

from __future__ import annotations

import json

import pytest

from evalglass.core.aggregation import AggregatedMetric
from evalglass.core.authority import AuthorityLevel, ResolvedAuthority
from evalglass.core.contracts import ContractError, Diagnostic, Severity
from evalglass.core.provenance import BaselineState, RunFingerprint
from evalglass.core.registry import Aggregation
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.core.verdict import GateInput, VerdictPayload, decide_verdict


def _verdict() -> VerdictPayload:
    gate = GateInput(
        metric="exact_match",
        resolved=ResolvedAuthority(can_gate=True, level=AuthorityLevel.GATING, blocked=False),
        value=0.9,
        threshold=0.8,
    )
    return decide_verdict([gate])


def _scorecard() -> Scorecard:
    return Scorecard(
        verdict=_verdict(),
        metrics=[
            # Consistent with the RunRecord's single scored 1.0 (M7 T5 recompute-on-load).
            AggregatedMetric(
                metric="exact_match",
                aggregation=Aggregation.MEAN,
                value=1.0,
                included_count=1,
                status_counts={"scored": 1},
            )
        ],
        authority={
            "exact_match": ResolvedAuthority(
                can_gate=True, level=AuthorityLevel.GATING, blocked=False
            )
        },
        baseline_state=BaselineState.COMPARABLE,
        diagnostics=[Diagnostic(code="info.note", severity=Severity.INFO, message="ok")],
    )


def _dims() -> dict[str, object]:
    return {
        d: f"{d}-v1"
        for d in (
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
        )
    }


def _scored() -> Score:
    return Score(
        metric="exact_match",
        value=1.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="exact_match@1",
    )


def _run_record() -> RunRecord:
    return RunRecord(
        run_id="run-1",
        scorecard=_scorecard(),
        scores=[_scored()],
        provenance=RunFingerprint.of(_dims()),
    )


def test_scorecard_round_trips() -> None:
    sc = _scorecard()
    assert Scorecard.from_dict(json.loads(json.dumps(sc.to_dict()))) == sc


def test_scorecard_exposes_verdict_and_baseline() -> None:
    payload = _scorecard().to_dict()
    assert payload["verdict"]["verdict"] == "pass"
    assert payload["baseline_state"] == "comparable"
    assert payload["metrics"][0]["metric"] == "exact_match"


def test_run_record_round_trips() -> None:
    rr = _run_record()
    assert RunRecord.from_dict(json.loads(json.dumps(rr.to_dict()))) == rr


def test_run_record_carries_individual_scores_and_provenance() -> None:
    payload = _run_record().to_dict()
    assert payload["run_id"] == "run-1"
    assert payload["scores"][0]["metric"] == "exact_match"
    assert "dimensions" in payload["provenance"]


@pytest.mark.parametrize("missing", ["verdict", "metrics", "authority"])
def test_scorecard_missing_required_fails(missing: str) -> None:
    data = _scorecard().to_dict()
    del data[missing]
    with pytest.raises(ContractError):
        Scorecard.from_dict(data)


def test_run_record_missing_required_fails() -> None:
    data = _run_record().to_dict()
    del data["scorecard"]
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_run_record_non_mapping_fails() -> None:
    with pytest.raises(ContractError):
        RunRecord.from_dict(["not", "a", "record"])  # type: ignore[arg-type]


def test_run_record_requires_scores_key() -> None:
    """The complete artifact must not silently parse as a run with no scores."""
    data = _run_record().to_dict()
    del data["scores"]
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_run_record_malformed_comparable_fails() -> None:
    data = _run_record().to_dict()
    data["comparable"] = "corrupt-not-a-fingerprint"
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_scorecard_unknown_baseline_state_fails() -> None:
    data = _scorecard().to_dict()
    data["baseline_state"] = "kinda_comparable"
    with pytest.raises(ContractError):
        Scorecard.from_dict(data)


# --- lane_results side channel (EG-H0-3; ADR 0031) --------------------------

_LANE_RESULT = {
    "lane": "score-sink-export",
    "status": "ran",
    "report": "exported scorecard",
    "diagnostics": [],
}


def _run_record_with_lanes() -> RunRecord:
    return RunRecord(
        run_id="run-1",
        scorecard=_scorecard(),
        scores=[_scored()],
        provenance=RunFingerprint.of(_dims()),
        lane_results=[dict(_LANE_RESULT)],
    )


def test_lane_results_default_empty() -> None:
    """A run with no configured lanes carries an empty side channel."""
    assert _run_record().lane_results == []


def test_lane_results_omitted_from_to_dict_when_empty() -> None:
    """An empty side channel is absent from the JSON, so no-lane runs stay byte-identical."""
    assert "lane_results" not in _run_record().to_dict()


def test_lane_results_present_in_to_dict() -> None:
    payload = _run_record_with_lanes().to_dict()
    assert payload["lane_results"] == [_LANE_RESULT]


def test_run_record_with_lane_results_round_trips() -> None:
    rr = _run_record_with_lanes()
    assert RunRecord.from_dict(json.loads(json.dumps(rr.to_dict()))) == rr


def test_old_artifact_without_lane_results_parses_to_empty() -> None:
    """An old RunRecord JSON (no lane_results key) parses with an empty side channel."""
    data = _run_record().to_dict()
    assert "lane_results" not in data
    assert RunRecord.from_dict(data).lane_results == []


def test_lane_results_must_be_a_list() -> None:
    data = _run_record_with_lanes().to_dict()
    data["lane_results"] = "not-a-list"
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_lane_results_entries_must_be_mappings() -> None:
    data = _run_record().to_dict()
    data["lane_results"] = [1, 2, 3]
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_scorecard_stays_lane_free() -> None:
    """The verdict-bearing summary never carries the lane side channel (ADR 0031)."""
    assert "lane_results" not in _scorecard().to_dict()


def test_to_dict_lane_results_is_a_copy() -> None:
    """Mutating the emitted JSON never reaches back into the frozen record."""
    rr = _run_record_with_lanes()
    payload = rr.to_dict()
    payload["lane_results"].append({"lane": "injected"})
    assert len(rr.to_dict()["lane_results"]) == 1
