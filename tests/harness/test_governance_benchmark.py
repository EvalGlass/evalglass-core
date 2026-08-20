"""Governance 1C — benchmark evidence never creates threshold approval (EG-AT2-3).

Source: alignment test plan §6 Part 1C.

A benchmark can *support* a threshold a host later approves, but it can never
*approve* one: only a host-owned ``ApprovedThreshold`` (with a real approver,
rationale, and variance) carries approval. ``approve_threshold_from_benchmark``
always raises, ``supports`` is informational (returns ``bool``), and no attribute
on ``BenchmarkEvidence`` hands back an ``ApprovedThreshold``.

Pure, hermetic unit tests in a new file; the frozen canary ``test_governance.py``
stays byte-stable (AT1 FS-META).
"""

from __future__ import annotations

import pytest

from evalglass.core import Direction
from evalglass.harness.calibration import ApprovedThreshold
from evalglass.harness.governance import (
    BenchmarkEvidence,
    GovernanceError,
    approve_threshold_from_benchmark,
)

# (observed, runs) — a benchmark can never approve regardless of how good it looks.
_OBSERVED_RUNS = [(0.0, 1), (1.0, 1), (0.5, 10_000), (-1.0, 1)]


def _host_approved(direction: Direction, value: float = 0.5) -> ApprovedThreshold:
    """A legitimately host-owned approval (the only path that carries approval)."""
    return ApprovedThreshold(
        value=value,
        direction=direction,
        variance=0.01,
        approver="host:rev-1",
        rationale="approved by host reviewer",
        version="1",
    )


@pytest.mark.parametrize(("observed", "runs"), _OBSERVED_RUNS)
def test_approve_from_benchmark_always_raises(observed: float, runs: int) -> None:
    """No observed value or run count lets a benchmark approve a threshold."""
    evidence = BenchmarkEvidence(metric="faithfulness", observed=observed, runs=runs)
    with pytest.raises(GovernanceError):
        approve_threshold_from_benchmark(evidence)


def test_benchmark_supports_returns_bool_only() -> None:
    """``supports`` is informational: it returns a plain ``bool``, never an approval."""
    higher = _host_approved(Direction.HIGHER_IS_BETTER, value=0.5)
    lower = _host_approved(Direction.LOWER_IS_BETTER, value=0.2)

    clears_high = BenchmarkEvidence(metric="m", observed=0.9, runs=3).supports(higher)
    misses_high = BenchmarkEvidence(metric="m", observed=0.1, runs=3).supports(higher)
    clears_low = BenchmarkEvidence(metric="m", observed=0.1, runs=3).supports(lower)
    misses_low = BenchmarkEvidence(metric="m", observed=0.9, runs=3).supports(lower)

    for result in (clears_high, misses_high, clears_low, misses_low):
        assert type(result) is bool
    assert clears_high is True
    assert misses_high is False
    assert clears_low is True
    assert misses_low is False


def test_no_benchmark_attribute_returns_an_approved_threshold() -> None:
    """Negative attribute probe: nothing on ``BenchmarkEvidence`` yields an approval."""
    evidence = BenchmarkEvidence(metric="m", observed=0.9, runs=3)
    for name in dir(evidence):
        if name.startswith("_"):
            continue
        attr = getattr(evidence, name)
        assert not isinstance(attr, ApprovedThreshold), name
    # The one method that takes a threshold returns a bool, not an approval.
    assert not isinstance(
        evidence.supports(_host_approved(Direction.HIGHER_IS_BETTER)), ApprovedThreshold
    )


def test_host_owned_approved_threshold_still_works() -> None:
    """Specificity: a real host-owned ``ApprovedThreshold`` is a usable approval.

    The host path (constructing an ``ApprovedThreshold`` with an approver, rationale,
    and variance) is the *only* way to get an approval — and it works, so the control
    above is not merely refusing every threshold.
    """
    approved = _host_approved(Direction.HIGHER_IS_BETTER, value=0.5)
    assert isinstance(approved, ApprovedThreshold)
    assert approved.approver == "host:rev-1"
    assert BenchmarkEvidence(metric="m", observed=0.6, runs=3).supports(approved) is True
