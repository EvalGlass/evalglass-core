"""First-class evaluability through a real run (Epic D / D3).

A run persists a per-metric ``PopulationSummary`` that reconciles the plan's pre-effect coverage
with the raw scores' terminal states, survives a round-trip, and fails closed on a tampered count.
Partial evaluability never renders as full coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import ContractError, RunRecord
from evalglass.core.population import PopulationSummary
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.runner import run_config


def _cfg(tmp_path: Path, rows: list[dict[str, object]], **metric_over: object) -> RuntimeConfig:
    (tmp_path / "d.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    metric: dict[str, object] = {
        "name": "correctness",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": "d.jsonl",
    }
    metric.update(metric_over)
    return RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [metric],
        }
    )


def _population(record: RunRecord, metric: str) -> PopulationSummary:
    return next(p for p in record.scorecard.populations if p.metric == metric)


def test_partial_evaluability_reconciles_and_is_not_full_coverage(tmp_path: Path) -> None:
    # 1 record has a reference (eligible+scored), 3 lack one (prerequisite-excluded).
    rows: list[dict[str, object]] = [{"input": "4", "output": "4", "reference": "4"}]
    rows += [{"input": str(i), "output": str(i)} for i in range(3)]
    record = run_config(_cfg(tmp_path, rows), tmp_path)
    pop = _population(record, "correctness")
    assert pop.available == 4
    assert pop.eligible == 1  # only the referenced row is eligible for a reference metric
    assert pop.prerequisite_excluded == 3
    assert pop.scored_valid == 1
    assert pop.scored_valid < pop.available  # 1 of 4 available -> not fully evaluable


def test_population_round_trips_and_persists(tmp_path: Path) -> None:
    record = run_config(_cfg(tmp_path, [{"input": "4", "output": "4", "reference": "4"}]), tmp_path)
    restored = RunRecord.from_dict(record.to_dict())
    assert restored.scorecard.populations == record.scorecard.populations
    assert _population(restored, "correctness").available == 1


def test_tampered_terminal_count_fails_closed(tmp_path: Path) -> None:
    record = run_config(_cfg(tmp_path, [{"input": "4", "output": "4", "reference": "4"}]), tmp_path)
    payload = record.to_dict()
    # Inflate scored_valid without changing the raw scores -> internally inconsistent.
    payload["scorecard"]["populations"][0]["scored_valid"] = 99
    with pytest.raises(ContractError, match="population"):
        RunRecord.from_dict(payload)


def test_bound_metric_scores_only_its_candidate_source(tmp_path: Path) -> None:
    # A metric bound to one dataset must not also score records from an unrelated source in the run:
    # its scored population equals its planned population (available), never the whole run.
    (tmp_path / "gold.jsonl").write_text(
        json.dumps({"input": "q", "output": {"answer": "yes"}}) + "\n", encoding="utf-8"
    )
    (tmp_path / "noise.jsonl").write_text(
        json.dumps({"input": "q2", "output": {"other": "no"}}) + "\n", encoding="utf-8"
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [
                {
                    "path": "gold.jsonl",
                    "name": "gold",
                    "status": "validated",
                    "data_policy": "permitted",
                },
                {
                    "path": "noise.jsonl",
                    "name": "noise",
                    "status": "validated",
                    "data_policy": "permitted",
                },
            ],
            "metrics": [
                {
                    "name": "presence",
                    "evaluator_ref": "field_presence@1",
                    "lens": "non_reference",
                    "score_type": "continuous",
                    "score_range": [0, 1],
                    "params": {"required_fields": ["answer"]},
                    "sources": [{"name": "gold", "role": "candidate"}],
                }
            ],
        }
    )
    record = run_config(cfg, tmp_path)
    pop = _population(record, "presence")
    assert pop.available == 1  # only the bound gold source
    assert pop.scored_valid == 1  # scored ONLY gold, not the unrelated noise record
    # And the metric's raw scores are exactly one (the gold subject), not two.
    assert sum(1 for s in record.scores if s.metric == "presence") == 1


def test_selector_no_match_is_visible_not_full_coverage(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = [
        {"input": "4", "output": "4", "reference": "4", "metadata": {"wf": "a"}}
    ]
    record = run_config(_cfg(tmp_path, rows, applies_to={"wf": "nope"}), tmp_path)
    pop = _population(record, "correctness")
    assert pop.available == 1
    assert pop.selector_matched == 0
    assert pop.selector_excluded == 1
    assert pop.scored_valid == 0  # nothing scored; the metric is not "fully evaluable"
