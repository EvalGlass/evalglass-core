"""Persist complete judge evidence in the RunRecord (ADR 0054, C4).

An archived run carries the parsed judge evidence — score, rationale, facets, violations, citations,
instrument refs, usage — that produced each judge Score, resolvable from ``Score.evidence_refs``
with no host cache. The evidence is integrity-covered: a dangling ref or a numeric value whose
evidence is not ``ok`` fails to load. Raw provider text is dropped by default (the fingerprint
stays) and kept only on opt-in. A legacy RunRecord with no evidence still loads. ``urlopen`` faked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import (
    ContractError,
    JudgeEvidence,
    JudgeEvidenceStatus,
    RunRecord,
    ScoreStatus,
)
from tests.harness.test_judge_openai_route import _completion, _patch_transport


def _judge_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    *,
    judge_extra: dict[str, Any] | None = None,
    data_policy: str = "permitted",
) -> RunRecord:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a"}) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("EG_JUDGE_KEY", "sk-secret")
    _patch_transport(monkeypatch, payload, [])
    from evalglass.harness.config import RuntimeConfig
    from evalglass.harness.runner import run_config

    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": data_policy}],
        "judge": {
            "adapter": "openai_compatible",
            "endpoint": "https://judge.test/v1/chat/completions",
            "model": "m",
            "credential_env": "EG_JUDGE_KEY",
            **(judge_extra or {}),
        },
        "metrics": [
            {
                "name": "faithfulness",
                "evaluator_ref": "judge_score@1",
                "lens": "non_reference",
                "score_type": "continuous",
                "score_range": [0.0, 1.0],
                "required_evidence": ["judge"],
            }
        ],
    }
    return run_config(RuntimeConfig.from_mapping(raw), tmp_path)


# --------------------------------------------------------------------------- #
# Persisted evidence resolves from the score
# --------------------------------------------------------------------------- #


def test_score_resolves_to_its_persisted_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.75, "grounded"))
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is ScoreStatus.SCORED
    assert score.evidence_refs  # AC1: a judge score has a resolvable ref
    evidence = record.resolve_evidence(score.evidence_refs[0])
    assert evidence is not None
    assert evidence.status is JudgeEvidenceStatus.OK
    assert evidence.parsed_value == pytest.approx(0.75)
    assert evidence.rationale == "grounded"


def test_evidence_round_trips_through_the_runrecord(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6))
    assert record.evidence  # non-empty
    reloaded = RunRecord.from_dict(record.to_dict())
    assert reloaded == record


def test_scorecard_stays_compact_no_evidence_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6))
    assert "evidence" in record.to_dict()
    assert "evidence" not in record.scorecard.to_dict()


# --------------------------------------------------------------------------- #
# Raw-response retention policy
# --------------------------------------------------------------------------- #


def test_raw_response_is_dropped_by_default_but_fingerprint_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6))
    evidence = record.evidence[0]
    assert evidence.raw_response is None  # conservative default
    assert evidence.response_fingerprint is not None  # still portable/verifiable


def test_raw_response_is_kept_when_the_host_opts_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(
        tmp_path, monkeypatch, _completion(0.6), judge_extra={"retain_raw_response": True}
    )
    assert record.evidence[0].raw_response is not None


# --------------------------------------------------------------------------- #
# Integrity: dangling ref / value-without-OK / legacy
# --------------------------------------------------------------------------- #


def test_dangling_evidence_ref_fails_to_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6))
    data = record.to_dict()
    # Tamper: keep the score's judge ref but drop the evidence record it points to.
    data["evidence"] = [e for e in data["evidence"] if e["metric"] != "faithfulness"]
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_value_without_ok_evidence_fails_to_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6))
    data = record.to_dict()
    # Tamper: flip the evidence status to a non-ok value while the score keeps its number.
    # (Drop parsed_value too, since an ok-only field cannot ride a non-ok status.)
    for e in data["evidence"]:
        if e["metric"] == "faithfulness":
            e["status"] = "provider_error"
            e.pop("parsed_value", None)
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)


def test_legacy_runrecord_without_evidence_still_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6))
    data = record.to_dict()
    # A pre-C4 archive: the judge score keeps its ref, but there is no evidence collection at all.
    data.pop("evidence", None)
    reloaded = RunRecord.from_dict(data)  # loads (legacy); refs are simply unavailable
    score = next(s for s in reloaded.scores if s.metric == "faithfulness")
    assert reloaded.resolve_evidence(score.evidence_refs[0]) is None


def test_blocked_judge_score_references_its_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A forbidden-egress subject: the judge is never called, evidence is MISSING, the score blocks —
    # and it still references the MISSING evidence record so a report can explain the block.
    record = _judge_run(tmp_path, monkeypatch, _completion(0.6), data_policy="forbidden")
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is ScoreStatus.BLOCKED
    assert score.value is None
    assert score.evidence_refs
    evidence = record.resolve_evidence(score.evidence_refs[0])
    assert evidence is not None
    assert evidence.status is JudgeEvidenceStatus.MISSING


def test_evidence_record_round_trips_standalone() -> None:
    e = JudgeEvidence(
        example_id="e1",
        metric="m",
        status=JudgeEvidenceStatus.OK,
        parsed_value=0.9,
        facets={"support": 0.9},
        citations=["input"],
    )
    assert e.evidence_id == "judge:e1:m"
    assert JudgeEvidence.from_dict(e.to_dict()) == e
