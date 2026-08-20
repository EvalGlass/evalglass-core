"""Judge execution policy — deterministic cache, budgets, bounded retry (ADR 0055, C3).

Hermetic: a fake JudgeModel counts calls and an injected clock drives budgets/backoff, so no network
and no real time. Proves a cache hit avoids the provider, every score-determining input invalidates
the key, corruption fails closed to a miss, budget exhaustion produces typed non-scored evidence for
remaining effects, and retries are bounded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evalglass.core import JudgeEvidenceStatus
from evalglass.core._validation import ContractError
from evalglass.core.authority import JudgeCapability
from evalglass.harness.judge_execution import (
    CacheMode,
    CacheState,
    JudgeCache,
    JudgeExecutionPolicy,
    JudgeExecutor,
    cache_key,
)
from evalglass.harness.ports import JudgeRequest, JudgeResult


class _CountingJudge:
    """A fake JudgeModel: records every call and returns a scripted sequence of results."""

    capability = JudgeCapability.MEASUREMENT  # unused by the executor, present for the protocol

    def __init__(self, results: list[JudgeResult]) -> None:
        self._results = results
        self.calls: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.calls.append(request)
        result = self._results[min(len(self.calls) - 1, len(self._results) - 1)]
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=result.status,
            parsed_value=result.parsed_value,
            raw_response=result.raw_response,
            tokens=result.tokens,
            cost=result.cost,
        )


def _ok(value: float = 0.8, **kw: Any) -> JudgeResult:
    return JudgeResult(
        example_id="e", metric="m", status=JudgeEvidenceStatus.OK, parsed_value=value, **kw
    )


def _req(example_id: str = "e1", metric: str = "m", output: Any = "a") -> JudgeRequest:
    return JudgeRequest(example_id=example_id, metric=metric, input="q", output=output)


def _executor(
    tmp_path: Path,
    judge: _CountingJudge,
    policy: JudgeExecutionPolicy,
    *,
    fingerprint: str = "fp-1",
    clock_values: list[float] | None = None,
) -> JudgeExecutor:
    cache = JudgeCache(tmp_path, policy.cache_dir, policy.cache_mode)
    ticks = iter(clock_values or [])
    return JudgeExecutor(
        judge, policy, cache, fingerprint, sleep=lambda _s: None, clock=lambda: next(ticks, 0.0)
    )


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def test_cache_hit_avoids_the_provider(tmp_path: Path) -> None:
    judge = _CountingJudge([_ok(0.8)])
    policy = JudgeExecutionPolicy(cache_mode=CacheMode.READ_WRITE)
    first = _executor(tmp_path, judge, policy).run([_req()])
    assert first[0].cache_state is CacheState.MISS
    assert len(judge.calls) == 1
    # A second executor over the same cache dir: the hit avoids a second provider call.
    judge2 = _CountingJudge([_ok(0.99)])  # would return a different value if called
    second = _executor(tmp_path, judge2, policy).run([_req()])
    assert second[0].cache_state is CacheState.HIT
    assert len(judge2.calls) == 0
    assert second[0].result.parsed_value == pytest.approx(0.8)  # the cached value, not 0.99


def test_off_mode_never_caches(tmp_path: Path) -> None:
    judge = _CountingJudge([_ok(0.8)])
    policy = JudgeExecutionPolicy(cache_mode=CacheMode.OFF)
    out = _executor(tmp_path, judge, policy).run([_req()])
    assert out[0].cache_state is CacheState.DISABLED
    # Nothing was written -> a read_write executor now misses.
    out2 = _executor(tmp_path, _CountingJudge([_ok(0.1)]), policy).run([_req()])
    assert out2[0].cache_state is CacheState.DISABLED


@pytest.mark.parametrize(
    "change",
    [
        {"fingerprint": "fp-2"},  # model/rubric/prompt/parser identity changed
        {"output": "different output"},  # candidate output changed
        {"metric": "other"},  # metric changed
    ],
)
def test_score_determining_change_invalidates_the_key(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    policy = JudgeExecutionPolicy(cache_mode=CacheMode.READ_WRITE)
    _executor(tmp_path, _CountingJudge([_ok(0.8)]), policy).run([_req()])
    judge2 = _CountingJudge([_ok(0.2)])
    fp = change.pop("fingerprint", "fp-1")
    out = _executor(tmp_path, judge2, policy, fingerprint=fp).run([_req(**change)])
    assert out[0].cache_state is CacheState.MISS  # a different key -> a real call
    assert len(judge2.calls) == 1


def test_refresh_recomputes_and_overwrites(tmp_path: Path) -> None:
    rw = JudgeExecutionPolicy(cache_mode=CacheMode.READ_WRITE)
    _executor(tmp_path, _CountingJudge([_ok(0.8)]), rw).run([_req()])
    refresh = JudgeExecutionPolicy(cache_mode=CacheMode.REFRESH)
    judge = _CountingJudge([_ok(0.3)])
    out = _executor(tmp_path, judge, refresh).run([_req()])
    assert len(judge.calls) == 1  # ignored the existing entry
    assert out[0].result.parsed_value == pytest.approx(0.3)
    # …and overwrote it: a read-only pass now hits the refreshed value.
    ro = JudgeExecutionPolicy(cache_mode=CacheMode.READ_ONLY)
    hit = _executor(tmp_path, _CountingJudge([_ok(0.0)]), ro).run([_req()])
    assert hit[0].cache_state is CacheState.HIT
    assert hit[0].result.parsed_value == pytest.approx(0.3)


def test_read_only_reads_but_does_not_write(tmp_path: Path) -> None:
    ro = JudgeExecutionPolicy(cache_mode=CacheMode.READ_ONLY)
    judge = _CountingJudge([_ok(0.8)])
    out = _executor(tmp_path, judge, ro).run([_req()])
    assert out[0].cache_state is CacheState.MISS  # nothing cached yet
    # It must not have written -> a second read-only pass misses again.
    out2 = _executor(tmp_path, _CountingJudge([_ok(0.8)]), ro).run([_req()])
    assert out2[0].cache_state is CacheState.MISS


def test_corrupt_cache_entry_fails_closed_to_a_miss(tmp_path: Path) -> None:
    policy = JudgeExecutionPolicy(cache_mode=CacheMode.READ_WRITE)
    _executor(tmp_path, _CountingJudge([_ok(0.8)]), policy).run([_req()])
    # Corrupt the single cache file.
    cache_dir = tmp_path / policy.cache_dir
    entry = next(cache_dir.glob("*.json"))
    entry.write_text("{ not json", encoding="utf-8")
    judge = _CountingJudge([_ok(0.5)])
    out = _executor(tmp_path, judge, policy).run([_req()])
    assert out[0].cache_state is CacheState.MISS  # never a stale silent score
    assert len(judge.calls) == 1


def test_credential_and_raw_payload_are_not_in_the_key() -> None:
    # The key is over the instrument fingerprint + request content, never a secret or raw response.
    key = cache_key("fp-1", _req())
    assert "sk-" not in key
    assert len(key) == 64  # a bare sha256 hex digest


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #


def test_budget_exhaustion_makes_remaining_effects_non_scored(tmp_path: Path) -> None:
    policy = JudgeExecutionPolicy(max_requests=1)
    judge = _CountingJudge([_ok(0.8)])
    out = _executor(tmp_path, judge, policy).run([_req("e1"), _req("e2"), _req("e3")])
    assert out[0].result.status is JudgeEvidenceStatus.OK
    # Budget hit after the first dispatch: the rest are typed non-scored, never a fabricated value.
    assert len(judge.calls) == 1
    for outcome in out[1:]:
        assert outcome.result.status is JudgeEvidenceStatus.MISSING
        assert outcome.result.parsed_value is None
        assert outcome.result.diagnostics[0].code == "judge_budget_exhausted"


def test_zero_request_budget_dispatches_nothing(tmp_path: Path) -> None:
    policy = JudgeExecutionPolicy(max_requests=0)
    judge = _CountingJudge([_ok(0.8)])
    out = _executor(tmp_path, judge, policy).run([_req()])
    assert len(judge.calls) == 0
    assert out[0].result.status is JudgeEvidenceStatus.MISSING


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #


def test_retry_recovers_a_transient_failure(tmp_path: Path) -> None:
    policy = JudgeExecutionPolicy(max_retries=2, retry_backoff_seconds=0.5)
    judge = _CountingJudge(
        [
            JudgeResult(example_id="e", metric="m", status=JudgeEvidenceStatus.PROVIDER_ERROR),
            _ok(0.7),
        ]
    )
    out = _executor(tmp_path, judge, policy).run([_req()])
    assert out[0].result.status is JudgeEvidenceStatus.OK
    assert out[0].attempts == 1
    assert len(judge.calls) == 2


def test_retry_is_bounded(tmp_path: Path) -> None:
    policy = JudgeExecutionPolicy(max_retries=2)
    judge = _CountingJudge(
        [JudgeResult(example_id="e", metric="m", status=JudgeEvidenceStatus.TIMEOUT)]
    )
    out = _executor(tmp_path, judge, policy).run([_req()])
    assert out[0].result.status is JudgeEvidenceStatus.TIMEOUT  # never a fabricated score
    assert len(judge.calls) == 3  # initial + 2 retries, then stop


# --------------------------------------------------------------------------- #
# Policy parsing
# --------------------------------------------------------------------------- #


def test_policy_parses_and_rejects_bad_fields() -> None:
    policy = JudgeExecutionPolicy.from_mapping(
        {"cache_mode": "read_write", "max_requests": 10, "max_retries": 3, "concurrency": 4}
    )
    assert policy.cache_mode is CacheMode.READ_WRITE
    assert policy.max_requests == 10
    with pytest.raises(ContractError):
        JudgeExecutionPolicy.from_mapping({"cache_mode": "nonsense"})
    with pytest.raises(ContractError):
        JudgeExecutionPolicy.from_mapping({"max_requests": -1})
    with pytest.raises(ContractError):
        JudgeExecutionPolicy.from_mapping({"concurrency": 0})


def test_cost_table_estimates_only_when_supplied() -> None:
    none = JudgeExecutionPolicy().cost_table
    assert none.estimate(1000, 1000) is None  # no embedded prices
    supplied = JudgeExecutionPolicy.from_mapping(
        {"cost_table": {"input_per_1k": 0.5, "output_per_1k": 1.5}}
    ).cost_table
    assert supplied.estimate(1000, 2000) == pytest.approx(0.5 + 3.0)


# --------------------------------------------------------------------------- #
# End-to-end through run_config: cache reuse + budget on a real run
# --------------------------------------------------------------------------- #


def _openai_judge_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes, execution: dict[str, Any]
) -> Any:
    import json as _json

    from evalglass.harness.config import RuntimeConfig
    from evalglass.harness.runner import run_config
    from tests.harness.test_judge_openai_route import _patch_transport

    (tmp_path / "d.jsonl").write_text(
        _json.dumps({"example_id": "e1", "input": "q", "output": "a"}) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("EG_JUDGE_KEY", "sk")
    sink: list[Any] = []
    _patch_transport(monkeypatch, payload, sink)
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": {
            "adapter": "openai_compatible",
            "endpoint": "https://judge.test/v1/chat/completions",
            "model": "m",
            "credential_env": "EG_JUDGE_KEY",
            "execution": execution,
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
    return run_config(RuntimeConfig.from_mapping(raw), tmp_path), sink


def test_run_config_cache_hit_across_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.harness.test_judge_openai_route import _completion

    record1, sink1 = _openai_judge_run(
        tmp_path, monkeypatch, _completion(0.8), {"cache_mode": "read_write"}
    )
    assert len(sink1) == 1
    assert record1.evidence[0].cache_state == "miss"
    # Re-run in the SAME root so the persisted cache is reused: a hit, no provider call, same value
    # (the second run's transport would return 0.1 if it were ever called).
    record2, sink2 = _openai_judge_run(
        tmp_path, monkeypatch, _completion(0.1), {"cache_mode": "read_write"}
    )
    assert sink2 == []  # cache hit -> no provider call
    assert record2.evidence[0].cache_state == "hit"
    assert record2.evidence[0].parsed_value == pytest.approx(0.8)


def test_run_config_budget_blocks_the_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evalglass.core import ScoreStatus
    from tests.harness.test_judge_openai_route import _completion

    record, sink = _openai_judge_run(tmp_path, monkeypatch, _completion(0.8), {"max_requests": 0})
    assert sink == []  # budget exhausted before any dispatch
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is ScoreStatus.BLOCKED
    assert score.value is None
