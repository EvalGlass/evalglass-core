"""Harness unit selector — group call-level trace units into richer aggregate units (EG-M5-5).

The call-level path is **unchanged**: ``select_units(..., kind=CALL)`` delegates to
:func:`evalglass.harness.prepare.example_from_trace`, one Example per call. When a non-call kind is
selected, the selector groups call-level :class:`TraceUnit`s sharing a ``trace_id`` into one
trajectory/session :class:`~evalglass.core.Example` whose ``output`` is the sequence of per-member
outputs and whose ``unit.members`` lists the sub-unit ids (ADR 0020). Only core ``Example``/
``EvalUnit`` cross to the evaluator — never a raw/vendor trace shape (build contract §6 trace rule).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence

from evalglass.core import EvalUnit, Example, UnitKind
from evalglass.harness.ports import TraceUnit
from evalglass.harness.prepare import example_from_trace


def aggregate_example(
    trace_units: Sequence[TraceUnit], *, kind: UnitKind, trace_id: str, unit_id: str
) -> Example:
    """Build one aggregate Example from the call-level trace units it spans (vendor-neutral)."""
    members = [tu.unit.unit_id for tu in trace_units]
    outputs = [tu.envelope.behavior.get("output") for tu in trace_units]
    inputs = [tu.envelope.behavior.get("input") for tu in trace_units]
    unit = EvalUnit(unit_id=unit_id, kind=kind, trace_id=trace_id, members=members)
    return Example(
        example_id=unit_id,
        input=inputs,
        output=outputs,
        unit=unit,
        context={"member_count": len(members)},
        metadata={"aggregate": kind.value},
        provenance={"members": members},
    )


def select_units(
    trace_units: Sequence[TraceUnit], *, kind: UnitKind = UnitKind.CALL
) -> list[Example]:
    """Convert normalized trace units to evaluator-ready Examples for the selected unit kind.

    ``kind=CALL`` is the unchanged call-level path. A richer kind groups call-level units by
    ``trace_id`` (insertion order preserved) into one aggregate Example each.
    """
    if kind is UnitKind.CALL:
        return [example_from_trace(tu) for tu in trace_units]
    groups: OrderedDict[str, list[TraceUnit]] = OrderedDict()
    for trace_unit in trace_units:
        groups.setdefault(trace_unit.unit.trace_id, []).append(trace_unit)
    return [
        aggregate_example(units, kind=kind, trace_id=trace_id, unit_id=f"{kind.value}:{trace_id}")
        for trace_id, units in groups.items()
    ]
