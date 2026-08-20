"""Judge execution policy: deterministic cache, budgets, and bounded retry (ADR 0055, C3).

Real judge work must be reproducible, cacheable, and bounded so a host can predict cost and never
trigger an uncontrolled burst of requests. This module wraps the per-effect judge call with:

- a **deterministic local cache** keyed by the complete score-determining instrument (the judge's
  non-secret identity + the rubric digest + the request content), with modes ``off`` /
  ``read_write`` / ``read_only`` / ``refresh``. A hit avoids the provider call and is marked in the
  evidence's cache state; a corrupt cache entry fails closed to a miss, never a stale silent score;
- **budgets** (max requests / total tokens / cost / wall time) checked **before** each dispatch —
  once exhausted, every remaining planned effect gets typed non-scored evidence, never a fabricated
  value; and
- **bounded retry** on a retryable status set (timeout / provider error), with a backoff whose sleep
  is injected so the required tier stays fast and deterministic.

Credentials and raw payloads are never cache keys. Cost is captured from provider usage when
present, else estimated from a host-supplied cost table (labelled an estimate) — the framework
embeds no prices. This module performs the cache file I/O (an effect); it computes no score.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evalglass.core import Diagnostic, JudgeEvidenceStatus, Severity
from evalglass.core._validation import (
    ContractError,
    _as_mapping,
    _coerce_enum,
    _opt_str,
)
from evalglass.harness._safe_fs import checked_target
from evalglass.harness.ports import JudgeModel, JudgeRequest, JudgeResult

_RETRYABLE = frozenset({JudgeEvidenceStatus.TIMEOUT, JudgeEvidenceStatus.PROVIDER_ERROR})
_CACHE_SCHEMA = "evalglass.judge-cache/1"


class CacheMode(enum.StrEnum):
    """How the local judge cache participates in a run."""

    OFF = "off"  # no cache read or write
    READ_WRITE = "read_write"  # read hits; write misses
    READ_ONLY = "read_only"  # read hits; never write
    REFRESH = "refresh"  # ignore existing entries; recompute and overwrite


class CacheState(enum.StrEnum):
    """The cache outcome recorded on a judge result's usage."""

    MISS = "miss"
    HIT = "hit"
    DISABLED = "disabled"


def _opt_pos_int(m: Mapping[str, Any], key: str, ctx: str) -> int | None:
    value = m.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{ctx}: '{key}' must be a non-negative integer, got {value!r}")
    return value


def _opt_pos_float(m: Mapping[str, Any], key: str, ctx: str) -> float | None:
    value = m.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ContractError(f"{ctx}: '{key}' must be a non-negative number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class CostTable:
    """A host-supplied cost table (per 1k tokens). Absent -> cost is captured-only."""

    input_per_1k: float | None = None
    output_per_1k: float | None = None
    label: str = "host-supplied"

    @property
    def available(self) -> bool:
        return self.input_per_1k is not None or self.output_per_1k is not None

    def estimate(self, input_tokens: int, output_tokens: int) -> float | None:
        if not self.available:
            return None
        return (input_tokens / 1000.0) * (self.input_per_1k or 0.0) + (output_tokens / 1000.0) * (
            self.output_per_1k or 0.0
        )


@dataclass(frozen=True)
class JudgeExecutionPolicy:
    """Typed, inspectable controls for real judge execution. Defaults reproduce the pre-C3 path."""

    cache_mode: CacheMode = CacheMode.OFF
    cache_dir: str = "reports/judge-cache"
    max_requests: int | None = None
    max_total_tokens: int | None = None
    max_cost: float | None = None
    max_wall_seconds: float | None = None
    max_retries: int = 0
    retry_backoff_seconds: float = 0.0
    concurrency: int = 1
    cost_table: CostTable = field(default_factory=CostTable)

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "judge.execution") -> JudgeExecutionPolicy:
        m = _as_mapping(data, ctx)
        cache_mode = _coerce_enum(CacheMode, m.get("cache_mode", "off"), "cache_mode", ctx)
        retries = _opt_pos_int(m, "max_retries", ctx) or 0
        concurrency = _opt_pos_int(m, "concurrency", ctx)
        if concurrency is not None and concurrency < 1:
            raise ContractError(f"{ctx}: 'concurrency' must be >= 1")
        cost_raw = _as_mapping(m.get("cost_table", {}), f"{ctx}.cost_table")
        return cls(
            cache_mode=cache_mode,
            cache_dir=_opt_str(m, "cache_dir", ctx) or "reports/judge-cache",
            max_requests=_opt_pos_int(m, "max_requests", ctx),
            max_total_tokens=_opt_pos_int(m, "max_total_tokens", ctx),
            max_cost=_opt_pos_float(m, "max_cost", ctx),
            max_wall_seconds=_opt_pos_float(m, "max_wall_seconds", ctx),
            max_retries=retries,
            retry_backoff_seconds=_opt_pos_float(m, "retry_backoff_seconds", ctx) or 0.0,
            concurrency=concurrency or 1,
            cost_table=CostTable(
                input_per_1k=_opt_pos_float(cost_raw, "input_per_1k", f"{ctx}.cost_table"),
                output_per_1k=_opt_pos_float(cost_raw, "output_per_1k", f"{ctx}.cost_table"),
                label=_opt_str(cost_raw, "label", f"{ctx}.cost_table") or "host-supplied",
            ),
        )


def cache_key(instrument_fingerprint: str, request: JudgeRequest) -> str:
    """A deterministic key over the instrument identity + the request content (never a secret).

    The instrument fingerprint carries the model/endpoint/rubric/prompt/parser identity (no
    credential); the request content is the input/output/reference/metric being judged. Changing any
    score-determining input changes the key, so a model or rubric change invalidates the cache.
    """
    body = json.dumps(
        {
            "schema": _CACHE_SCHEMA,
            "instrument": instrument_fingerprint,
            "metric": request.metric,
            "input": request.input,
            "output": request.output,
            "reference": request.reference,
            "rubric_ref": request.rubric_ref,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class JudgeCache:
    """A deterministic on-disk judge cache. Corruption fails closed to a miss (no stale score)."""

    def __init__(self, root: Path, cache_dir: str, mode: CacheMode) -> None:
        self._root = root
        self._cache_dir = cache_dir
        self._mode = mode
        self._enabled = mode is not CacheMode.OFF

    def _dir(self) -> Path:
        """The confined cache dir, validated fresh at each use (host-config path, fail-closed)."""
        return checked_target(self._root, self._root / self._cache_dir, what="judge cache dir")

    def _entry(self, base: Path, key: str) -> Path:
        """The confined path for a cache key under the (already-validated) base directory."""
        return checked_target(base, base / f"{key}.json", what="judge cache entry")

    def get(self, key: str) -> JudgeResult | None:
        """A cached result for ``key`` in the current mode, or ``None`` (miss/corrupt/refresh)."""
        if not self._enabled or self._mode is CacheMode.REFRESH:
            return None
        base = self._dir()
        if not base.is_dir():
            return None
        path = self._entry(base, key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _result_from_cache(data)
        except (OSError, ValueError):  # ContractError is a ValueError
            return None  # corrupt entry -> fail closed to a miss

    def put(self, key: str, result: JudgeResult) -> None:
        if not self._enabled or self._mode in (CacheMode.OFF, CacheMode.READ_ONLY):
            return
        base = self._dir()
        base.mkdir(parents=True, exist_ok=True)
        path = self._entry(base, key)
        tmp = checked_target(base, path.with_suffix(".json.tmp"), what="judge cache temp")
        tmp.write_text(json.dumps(_result_to_cache(result), sort_keys=True), encoding="utf-8")
        tmp.replace(path)  # atomic


def _result_to_cache(result: JudgeResult) -> dict[str, Any]:
    return {
        "schema": _CACHE_SCHEMA,
        "status": result.status.value,
        "parsed_value": result.parsed_value,
        "raw_response": result.raw_response,
        "rationale": result.rationale,
        "facets": dict(result.facets),
        "violations": list(result.violations),
        "citations": list(result.citations),
        "refusal_reason": result.refusal_reason,
        "tokens": result.tokens,
        "cost": result.cost,
    }


def _result_from_cache(data: Any) -> JudgeResult:
    m = _as_mapping(data, "judge-cache")
    status = _coerce_enum(JudgeEvidenceStatus, m.get("status"), "status", "judge-cache")
    return JudgeResult(
        example_id="",  # filled in by the executor for the concrete request
        metric="",
        status=status,
        parsed_value=m.get("parsed_value"),
        raw_response=m.get("raw_response"),
        rationale=m.get("rationale"),
        facets=dict(m.get("facets") or {}),
        violations=list(m.get("violations") or []),
        citations=list(m.get("citations") or []),
        refusal_reason=m.get("refusal_reason"),
        tokens=m.get("tokens"),
    )


@dataclass(frozen=True)
class ExecutionOutcome:
    """One effect's result plus how it was produced (cache state, attempts) — usage evidence."""

    result: JudgeResult
    cache_state: CacheState
    attempts: int


@dataclass
class _Budget:
    """Mutable run budget; ``exhausted`` is checked BEFORE each dispatch."""

    policy: JudgeExecutionPolicy
    requests: int = 0
    tokens: int = 0
    cost: float = 0.0
    elapsed: float = 0.0

    def exhausted(self) -> str | None:
        p = self.policy
        if p.max_requests is not None and self.requests >= p.max_requests:
            return "max_requests"
        if p.max_total_tokens is not None and self.tokens >= p.max_total_tokens:
            return "max_total_tokens"
        if p.max_cost is not None and self.cost >= p.max_cost:
            return "max_cost"
        if p.max_wall_seconds is not None and self.elapsed >= p.max_wall_seconds:
            return "max_wall_seconds"
        return None

    def record(self, result: JudgeResult, now: float, start: float) -> None:
        self.requests += 1
        self.tokens += result.tokens or 0
        self.cost += result.cost or 0.0
        self.elapsed = now - start


class JudgeExecutor:
    """Runs judge requests under a policy: cache, budget, and bounded retry, in deterministic order.

    ``sleep`` and ``clock`` are injected so the required tier is fast and deterministic. Concurrency
    is bounded by the policy; results are always returned in request order, keyed by plan effect id.
    """

    def __init__(
        self,
        judge: JudgeModel,
        policy: JudgeExecutionPolicy,
        cache: JudgeCache,
        instrument_fingerprint: str,
        *,
        sleep: Callable[[float], None] = lambda _s: None,
        clock: Callable[[], float] = lambda: 0.0,
    ) -> None:
        self._judge = judge
        self._policy = policy
        self._cache = cache
        self._fp = instrument_fingerprint
        self._sleep = sleep
        self._clock = clock

    def run(self, requests: Sequence[JudgeRequest]) -> list[ExecutionOutcome]:
        budget = _Budget(self._policy)
        start = self._clock()
        outcomes: list[ExecutionOutcome] = []
        for request in requests:
            reason = budget.exhausted()
            if reason is not None:
                outcomes.append(_budget_exhausted_outcome(request, reason))
                continue
            outcomes.append(self._one(request, budget, start))
        return outcomes

    def _one(self, request: JudgeRequest, budget: _Budget, start: float) -> ExecutionOutcome:
        key = cache_key(self._fp, request)
        cached = self._cache.get(key)
        if cached is not None:
            result = _rebind(cached, request)
            return ExecutionOutcome(result=result, cache_state=CacheState.HIT, attempts=0)
        result, attempts = self._dispatch_with_retry(request)
        budget.record(result, self._clock(), start)
        self._cache.put(key, result)
        state = CacheState.MISS if self._cache_enabled else CacheState.DISABLED
        return ExecutionOutcome(result=result, cache_state=state, attempts=attempts)

    @property
    def _cache_enabled(self) -> bool:
        return self._policy.cache_mode is not CacheMode.OFF

    def _dispatch_with_retry(self, request: JudgeRequest) -> tuple[JudgeResult, int]:
        attempt = 0
        result = self._judge.judge(request)
        while result.status in _RETRYABLE and attempt < self._policy.max_retries:
            attempt += 1
            if self._policy.retry_backoff_seconds > 0:
                self._sleep(self._policy.retry_backoff_seconds * attempt)
            result = self._judge.judge(request)
        return result, attempt


def _rebind(cached: JudgeResult, request: JudgeRequest) -> JudgeResult:
    from dataclasses import fields

    values = {f.name: getattr(cached, f.name) for f in fields(cached)}
    values["example_id"] = request.example_id
    values["metric"] = request.metric
    return JudgeResult(**values)


def _budget_exhausted_outcome(request: JudgeRequest, reason: str) -> ExecutionOutcome:
    result = JudgeResult(
        example_id=request.example_id,
        metric=request.metric,
        status=JudgeEvidenceStatus.MISSING,
        diagnostics=[
            Diagnostic(
                code="judge_budget_exhausted",
                severity=Severity.WARNING,
                message=f"judge budget exhausted ({reason}); this effect was not dispatched",
                location=request.example_id,
            )
        ],
    )
    return ExecutionOutcome(result=result, cache_state=CacheState.DISABLED, attempts=0)
