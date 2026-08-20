"""Trace → Example convergence (EG-M1-4).

A normalized ``TraceUnit`` becomes an evaluator-ready ``Example`` whose input/output come
from the envelope's vendor-neutral behavior — the evaluator never sees the envelope itself.
"""

from __future__ import annotations

from evalglass.core import DataPolicy, EvalUnit, Example, TraceEnvelope, UnitKind
from evalglass.harness.ports import TraceUnit
from evalglass.harness.prepare import example_from_trace


def _trace_unit(
    behavior: dict[str, object], metadata: dict[str, object] | None = None
) -> TraceUnit:
    return TraceUnit(
        envelope=TraceEnvelope(
            trace_id="t1",
            source="local_jsonl",
            behavior=behavior,
            data_policy=DataPolicy.PERMITTED,
            metadata=metadata or {},
        ),
        unit=EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1"),
    )


def test_trace_unit_becomes_example() -> None:
    ex = example_from_trace(_trace_unit({"input": "q", "output": "a"}))
    assert isinstance(ex, Example)
    assert ex.input == "q"
    assert ex.output == "a"
    assert ex.reference is None
    assert ex.unit.unit_id == "u1"


def test_trace_without_input_maps_output_only() -> None:
    ex = example_from_trace(_trace_unit({"output": "a"}))
    assert ex.input is None
    assert ex.output == "a"


def test_envelope_metadata_propagates_to_the_example() -> None:
    # Workflow-dispatch metadata (e.g. a connector's trace_name) must survive the trace route so a
    # host evaluator can dispatch by workflow — otherwise every metric reads as non_applicable.
    ex = example_from_trace(
        _trace_unit({"input": "q", "output": "a"}, metadata={"trace_name": "entity-extraction"})
    )
    assert ex.metadata["trace_name"] == "entity-extraction"
    assert ex.metadata["trace_source"] == "local_jsonl"  # still present
