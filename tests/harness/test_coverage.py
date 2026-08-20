"""Source import coverage manifest contract (Epic B, B2).

Sensitivity: a rejected/fallback/empty read derives the weaker completeness; a manifest round-trips
and fails closed on a malformed payload. Specificity: a clean full read is complete, and the typed
completeness cannot be silently upgraded.
"""

from __future__ import annotations

import pytest

from evalglass.core import DataPolicy, Diagnostic, Severity
from evalglass.harness.coverage import (
    SourceCompleteness,
    SourceImportManifest,
    availability_from_behaviors,
    derive_completeness,
)


def _manifest(**over: object) -> SourceImportManifest:
    base: dict[str, object] = {
        "source": "traces/x.jsonl",
        "kind": "trace",
        "adapter": "local_jsonl",
        "data_policy": DataPolicy.UNKNOWN,
        "completeness": SourceCompleteness.COMPLETE,
        "records_seen": 3,
        "units_emitted": 3,
    }
    base.update(over)
    return SourceImportManifest(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# derive_completeness — the single completeness rule (typed, never a percentage)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("seen", "emitted", "rejected", "fallback", "blocked", "expected"),
    [
        (3, 3, 0, 0, False, SourceCompleteness.COMPLETE),  # clean full read
        (0, 0, 0, 0, False, SourceCompleteness.EMPTY),  # empty-valid response
        (3, 2, 1, 0, False, SourceCompleteness.PARTIAL),  # a rejected record
        (2, 2, 0, 1, False, SourceCompleteness.PARTIAL),  # a trace-level fallback
        (3, 2, 0, 0, False, SourceCompleteness.PARTIAL),  # seen but not emitted
        (0, 0, 1, 0, True, SourceCompleteness.BLOCKED),  # egress refused / unreachable
        (5, 5, 0, 0, True, SourceCompleteness.BLOCKED),  # blocked wins outright
    ],
)
def test_completeness_rule(
    seen: int,
    emitted: int,
    rejected: int,
    fallback: int,
    blocked: bool,
    expected: SourceCompleteness,
) -> None:
    assert (
        derive_completeness(
            records_seen=seen,
            units_emitted=emitted,
            rejected=rejected,
            trace_level_fallback=fallback,
            blocked=blocked,
        )
        == expected
    )


def test_empty_valid_is_not_complete() -> None:
    """An empty-valid provider response is `empty`, never `complete` (B2 AC #2)."""
    assert (
        derive_completeness(records_seen=0, units_emitted=0, rejected=0) is SourceCompleteness.EMPTY
    )


# --------------------------------------------------------------------------- #
# Round-trip + fail-closed
# --------------------------------------------------------------------------- #


def test_round_trip_preserves_all_fields() -> None:
    m = _manifest(
        completeness=SourceCompleteness.PARTIAL,
        records_seen=5,
        units_emitted=3,
        rejected=2,
        trace_level_fallback=1,
        fmt="local",
        endpoint_label="provider endpoint",
        availability={"input": True, "application_output": False},
        diagnostics=[Diagnostic(code="c", severity=Severity.ERROR, message="m")],
        provenance={"provider": "langfuse"},
    )
    back = SourceImportManifest.from_dict(m.to_dict())
    assert back == m


def test_from_dict_fails_closed_on_missing_field() -> None:
    bad = _manifest().to_dict()
    del bad["records_seen"]
    with pytest.raises(ValueError, match="invalid source manifest"):
        SourceImportManifest.from_dict(bad)


def test_from_dict_fails_closed_on_bad_completeness() -> None:
    bad = _manifest().to_dict()
    bad["completeness"] = "totally_fine"  # not a real completeness state
    with pytest.raises(ValueError, match="invalid source manifest"):
        SourceImportManifest.from_dict(bad)


def test_reconciliation_counts() -> None:
    """records_seen reconciles to emitted + rejected for a record-oriented source (B2 AC #4)."""
    m = _manifest(
        records_seen=5, units_emitted=3, rejected=2, completeness=SourceCompleteness.PARTIAL
    )
    assert m.records_seen == m.units_emitted + m.rejected


# --------------------------------------------------------------------------- #
# availability
# --------------------------------------------------------------------------- #


def test_availability_reports_present_layers() -> None:
    avail = availability_from_behaviors(
        [{"input": "q", "output": "a", "model": "m"}, {"output": "b", "tool_calls": [{}]}]
    )
    assert avail["input"] is True
    assert avail["application_output"] is True
    assert avail["model_settings"] is True
    assert avail["tool_calls"] is True
    assert avail["usage"] is False  # never present → False, not omitted


def test_availability_all_false_when_nothing_emitted() -> None:
    avail = availability_from_behaviors([])
    assert set(avail.values()) == {False}
