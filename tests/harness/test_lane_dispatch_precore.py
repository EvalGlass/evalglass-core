"""Pre-core lane dispatch through run_config (EG-H0-5; ADR 0031).

A configured TRACE_SOURCE lane (trace-backend, async-observation) normalizes its spans to evidence
*before* the core, so its units join the run — and, carrying no gold, it dilutes worst-source
authority to ``proposed`` exactly like a built-in trace, so a gating metric cannot pass over it.
A missing source skips cleanly. The opt-in live-judge (JUDGE_MODEL) lane is never run in the
required tier: it is recorded as a skipped side-channel result and makes no network call.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import DataPolicy
from evalglass.harness import runner as runner_mod
from evalglass.harness.config import LaneConfig, RuntimeConfig
from evalglass.harness.lanes import LaneStatus, built_in_lanes
from evalglass.harness.runner import run_config


def _write_dataset(tmp_path: Path) -> None:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )


def _write_spans(tmp_path: Path, name: str = "be.json", n: int = 2) -> None:
    spans = [
        {"trace_id": f"t{i}", "attributes": {"input.value": f"q{i}", "output.value": f"a{i}"}}
        for i in range(n)
    ]
    (tmp_path / name).write_text(json.dumps({"spans": spans}), encoding="utf-8")


def _exact_match(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "dataset": "d.jsonl",
    }
    base.update(over)
    return base


def test_trace_backend_lane_runs_and_contributes_units(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    _write_spans(tmp_path, n=2)
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            "lanes": [
                {
                    "name": "trace-backend",
                    "enabled": True,
                    "options": {"backend_path": "be.json", "data_policy": "permitted"},
                }
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    backend = [r for r in record.lane_results if r["lane"] == "trace-backend"]
    assert len(backend) == 1
    assert backend[0]["status"] == "ran"
    assert "normalized" in backend[0]["report"]
    # The 2 trace units joined the 1 dataset example: every metric scores every example.
    assert len(record.scores) == 3


def test_async_observation_lane_contributes_units(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    _write_spans(tmp_path, name="rec.json", n=1)
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            "lanes": [
                {
                    "name": "async-observation",
                    "enabled": True,
                    "options": {"recording_path": "rec.json", "data_policy": "permitted"},
                }
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    obs = [r for r in record.lane_results if r["lane"] == "async-observation"]
    assert len(obs) == 1
    assert obs[0]["status"] == "ran"
    assert len(record.scores) == 2  # 1 dataset + 1 observed unit


def test_trace_lane_dilutes_gating_authority_to_proposed(tmp_path: Path) -> None:
    """The trust line: a gating metric on a validated+approved dataset gates — but adding a
    trace lane (no gold) dilutes worst-source authority to proposed, so it can no longer gate."""
    _write_dataset(tmp_path)
    gating = _exact_match(threshold=0.5, metric_status="gating", threshold_approval="approved")
    base_cfg = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "metrics": [gating],
    }
    # Without a lane the gating metric can gate (and passes).
    no_lane = run_config(RuntimeConfig.from_mapping(base_cfg), root=tmp_path)
    assert no_lane.scorecard.authority["exact_match"].can_gate is True
    assert no_lane.scorecard.verdict.verdict.value == "pass"

    # Adding a trace lane (no gold) dilutes authority → can no longer gate → informational.
    _write_spans(tmp_path, n=1)
    with_lane_cfg = {
        **base_cfg,
        "lanes": [
            {"name": "trace-backend", "enabled": True, "options": {"backend_path": "be.json"}}
        ],
    }
    with_lane = run_config(RuntimeConfig.from_mapping(with_lane_cfg), root=tmp_path)
    assert with_lane.scorecard.authority["exact_match"].can_gate is False
    assert with_lane.scorecard.verdict.verdict.value == "informational"


def test_trace_backend_lane_missing_source_skips(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            # enabled but an empty backend_path → "no source configured" → a clean skip
            "lanes": [{"name": "trace-backend", "enabled": True, "options": {"backend_path": ""}}],
        }
    )
    record = run_config(cfg, root=tmp_path)
    backend = [r for r in record.lane_results if r["lane"] == "trace-backend"]
    assert len(backend) == 1
    assert backend[0]["status"] == "skipped"
    assert len(record.scores) == 1  # only the dataset example; no units contributed


def test_live_judge_lane_is_opt_in_and_skipped_in_required_tier(tmp_path: Path) -> None:
    """A configured live-judge lane is never run in the required tier: it is a skipped side-channel
    result and makes no network call (the autouse hermetic guard would fail any egress)."""
    _write_dataset(tmp_path)
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            "lanes": [{"name": "live-judge", "enabled": True, "options": {}}],
        }
    )
    record = run_config(cfg, root=tmp_path)
    judge = [r for r in record.lane_results if r["lane"] == "live-judge"]
    assert len(judge) == 1
    assert judge[0]["status"] == "skipped"
    # the run still produced an honest verdict, unaffected by the opt-in lane
    assert record.scorecard.verdict.verdict.value in {"informational", "pass"}


def test_disabled_trace_lane_contributes_nothing(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    _write_spans(tmp_path, n=2)
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            "lanes": [
                {"name": "trace-backend", "enabled": False, "options": {"backend_path": "be.json"}}
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    assert record.lane_results == []
    assert len(record.scores) == 1  # disabled lane added no units


def test_trace_lane_declared_data_policy_reaches_the_adapter(tmp_path: Path) -> None:
    """A trace lane's top-level ``data_policy`` reaches its source adapter (no need to duplicate it
    inside options): the declared policy enters the worst-source trace policies."""
    _write_spans(tmp_path, n=1)
    loaded: list[object] = []
    source_names: list[str] = []
    diagnostics: list[object] = []
    policies: list[DataPolicy] = []
    result = runner_mod._run_trace_source_lane(
        built_in_lanes(),
        LaneConfig(
            name="trace-backend",
            enabled=True,
            data_policy=DataPolicy.PERMITTED,
            options={"backend_path": "be.json"},  # note: no data_policy here
        ),
        tmp_path,
        loaded,  # type: ignore[arg-type]
        source_names,
        diagnostics,  # type: ignore[arg-type]
        policies,
        [],  # source_manifests accumulator (B2)
    )
    assert result.status is LaneStatus.RAN
    assert policies == [DataPolicy.PERMITTED]  # the declared policy, not the "unknown" default
    assert source_names == ["trace-backend"]  # the lane unit's source name (D1)


def test_trace_lane_unavailable_source_is_blocked_not_a_hollow_ran(tmp_path: Path) -> None:
    """A read-level failure (missing/malformed backend) is a blocked lane result carrying the read
    diagnostics — never a hollow ``ran / normalized 0 unit(s)`` while the Scorecard shows a read
    error."""
    _write_dataset(tmp_path)
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            "lanes": [
                {"name": "trace-backend", "enabled": True, "options": {"backend_path": "gone.json"}}
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    backend = [r for r in record.lane_results if r["lane"] == "trace-backend"]
    assert len(backend) == 1
    assert backend[0]["status"] == "blocked"
    assert backend[0]["diagnostics"]  # the read diagnostics are carried on the lane result


def test_trace_lane_partial_success_carries_diagnostics_on_the_lane_result(tmp_path: Path) -> None:
    """Partial success (one valid + one malformed span): the lane RAN (the valid unit joins the
    run) AND the per-span mapping diagnostic is carried on the lane_result side channel — not a
    clean ``ran / 0 diagnostics`` that hides the partial mapping failure (audit P2-B). The Scorecard
    already carried the diagnostic; this only makes the additive side channel as faithful as the
    BLOCKED branch."""
    _write_dataset(tmp_path)
    spans = [
        {"trace_id": "t0", "attributes": {"input.value": "q", "output.value": "a"}},  # valid
        {"trace_id": "t1", "attributes": {"input.value": "q"}},  # no output -> mapping-incomplete
    ]
    (tmp_path / "be.json").write_text(json.dumps({"spans": spans}), encoding="utf-8")
    cfg = RuntimeConfig.from_mapping(
        {
            "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
            "metrics": [_exact_match()],
            "lanes": [
                {
                    "name": "trace-backend",
                    "enabled": True,
                    "options": {"backend_path": "be.json", "data_policy": "permitted"},
                }
            ],
        }
    )
    record = run_config(cfg, root=tmp_path)
    backend = [r for r in record.lane_results if r["lane"] == "trace-backend"]
    assert len(backend) == 1
    assert backend[0]["status"] == "ran"  # the valid unit joined the run
    assert backend[0]["diagnostics"], "the partial mapping diagnostic must ride on the lane result"
    assert any(d.get("code") == "trace_mapping_incomplete" for d in backend[0]["diagnostics"])
    assert "diagnostic" in backend[0]["report"]  # the report notes the diagnostic count
    # The valid unit joined the run (so >1 score beyond the dataset example); the Scorecard also
    # stays honest about the malformed span via a route-error score — the point here is that the
    # lane_result side channel ALSO carries the diagnostic, asserted above.
    assert len(record.scores) >= 2


def test_trace_lane_breaks_comparability_fingerprint(tmp_path: Path) -> None:
    """Adding a trace lane changes the gating provenance (config dimension), so a comparison
    cannot be silently reported comparable when the evidence source changed."""
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    _write_dataset(a)
    _write_dataset(b)
    _write_spans(b, n=1)
    base = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "metrics": [_exact_match()],
    }
    no_lane = run_config(RuntimeConfig.from_mapping(base), root=a)
    with_lane = run_config(
        RuntimeConfig.from_mapping(
            {
                **base,
                "lanes": [
                    {
                        "name": "trace-backend",
                        "enabled": True,
                        "options": {"backend_path": "be.json"},
                    }
                ],
            }
        ),
        root=b,
    )
    no_lane_config = no_lane.provenance.to_dict()["dimensions"]["config"]
    with_lane_config = with_lane.provenance.to_dict()["dimensions"]["config"]
    assert no_lane_config != with_lane_config
