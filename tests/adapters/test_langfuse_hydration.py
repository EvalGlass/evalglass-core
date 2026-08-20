"""Bounded Langfuse observation hydration (Epic B, B3 Part B).

A trace whose ``observations`` are bare IDs is hydrated into observation-level spans instead of a
single trace-level fallback; a partial hydration keeps the usable observations and reads partial;
hydration is bounded and stays hermetic (the SDK is never imported).
"""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.adapters.trace_langfuse import LangfuseTraceSource
from evalglass.harness.coverage import SourceCompleteness


def _source(payload: dict[str, Any]) -> LangfuseTraceSource:
    return LangfuseTraceSource(
        data_policy="permitted", endpoint="https://lf.example", fetch=lambda: payload
    )


def _obs(oid: str) -> dict[str, Any]:
    return {"id": oid, "input": f"in-{oid}", "output": {"answer": oid}, "model": "m"}


def test_bare_id_observations_are_hydrated_to_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"id": "t1", "observations": ["o1", "o2"], "output": "trace-out"}]}
    src = _source(payload)
    monkeypatch.setattr(
        LangfuseTraceSource,
        "_hydrate_observations",
        lambda self, trace_id, ids: [_obs(i) for i in ids],
    )
    read = src.read()
    # Two observation-level units, NOT one trace-level fallback.
    assert len(read.units) == 2
    outputs = {u.envelope.behavior["output"]["answer"] for u in read.units}
    assert outputs == {"o1", "o2"}
    m = read.manifest
    assert m is not None
    assert m.trace_level_fallback == 0  # hydrated, so no fallback
    assert m.completeness is SourceCompleteness.COMPLETE


def test_partial_hydration_keeps_usable_units_and_reads_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"data": [{"id": "t1", "observations": ["o1", "o2", "o3"], "output": "trace-out"}]}
    src = _source(payload)
    # Only one of three observations hydrates (the others failed) — a shortfall.
    monkeypatch.setattr(
        LangfuseTraceSource,
        "_hydrate_observations",
        lambda self, trace_id, ids: [_obs("o1")],
    )
    read = src.read()
    assert len(read.units) == 1  # the usable observation survives
    assert read.units[0].envelope.behavior["output"] == {"answer": "o1"}


def test_no_hydration_available_falls_back_to_trace_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"data": [{"id": "t1", "observations": ["o1", "o2"], "output": "trace-out"}]}
    src = _source(payload)
    # Hydration yields nothing (endpoint lacks it) -> trace-level fallback, as before.
    monkeypatch.setattr(
        LangfuseTraceSource, "_hydrate_observations", lambda self, trace_id, ids: []
    )
    read = src.read()
    assert len(read.units) == 1
    m = read.manifest
    assert m is not None
    assert m.trace_level_fallback == 1  # the fallback is visible in the manifest
    assert m.completeness is SourceCompleteness.PARTIAL


def test_full_object_observations_are_not_re_hydrated(monkeypatch: pytest.MonkeyPatch) -> None:
    # When observations are already full objects, hydration must not run.
    payload = {"data": [{"id": "t1", "observations": [_obs("o1")]}]}
    src = _source(payload)

    def _boom(self: object, trace_id: object, ids: object) -> list[Any]:
        raise AssertionError("hydration must not be called for full-object observations")

    monkeypatch.setattr(LangfuseTraceSource, "_hydrate_observations", _boom)
    read = src.read()
    assert len(read.units) == 1


def test_hydration_bounded_by_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [f"o{i}" for i in range(10)]
    payload = {"data": [{"id": "t1", "observations": ids, "output": "x"}]}
    src = _source(payload)
    monkeypatch.setattr(LangfuseTraceSource, "_MAX_HYDRATED_OBSERVATIONS", 3)
    seen: list[int] = []

    def _hydrate(self: object, trace_id: object, take: list[str]) -> list[dict[str, Any]]:
        seen.append(len(take))
        return [_obs(i) for i in take]

    monkeypatch.setattr(LangfuseTraceSource, "_hydrate_observations", _hydrate)
    src.read()
    assert seen == [3]  # only the ceiling number of observations were requested
