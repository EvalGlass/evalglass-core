"""Route convergence helpers — normalized sources to evaluator-ready Examples (EG-M1-4).

The dataset route already yields ``Example`` objects; the trace route yields ``TraceUnit``
(envelope + unit). ``example_from_trace`` turns the latter into an ``Example`` whose input and
output come from the envelope's vendor-neutral ``behavior`` — so the evaluator only ever sees
a core ``Example``, never the envelope or a raw/vendor trace shape.
"""

from __future__ import annotations

from evalglass.core import Example
from evalglass.harness.ports import TraceUnit


def example_from_trace(trace_unit: TraceUnit) -> Example:
    """Build an evaluator-ready ``Example`` from one normalized trace unit (no gold reference)."""
    behavior = trace_unit.envelope.behavior
    # Carry the envelope's metadata (e.g. a connector's ``trace_name``/``session`` for
    # workflow dispatch) onto the Example, then stamp the source — so a host evaluator can
    # dispatch by workflow without the envelope, which the vendor-neutral behavior alone omits.
    metadata = {**dict(trace_unit.envelope.metadata), "trace_source": trace_unit.envelope.source}
    return Example(
        example_id=trace_unit.unit.unit_id,
        input=behavior.get("input"),
        output=behavior.get("output"),
        unit=trace_unit.unit,
        reference=None,
        context={},
        metadata=metadata,
        provenance=dict(trace_unit.envelope.provenance),
    )
