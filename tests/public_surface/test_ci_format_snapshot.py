"""FS-SNAP-4 — freeze the CI annotation format (EG-AT1 Slice 2, EG-AT1-2).

The GitHub workflow-command output is byte-frozen for a clean run, and proven to
escape hostile host-derived strings: a metric name or diagnostic carrying ``%``,
``\\r``, ``\\n``, ``:``, or ``,`` cannot forge an extra ``::command`` line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.adapters.ci_annotation_sink import CiAnnotationSink
from evalglass.core import (
    AggregatedMetric,
    AuthorityLevel,
    Diagnostic,
    ResolvedAuthority,
    Scorecard,
    Severity,
    Verdict,
    VerdictPayload,
)
from evalglass.core.registry import Aggregation
from tests.public_surface._normalize import ci_command_count
from tests.scorecard_factory import informational_scorecard

_SNAP = Path(__file__).parent / "_snapshots"

#: A metric name packed with every character GitHub workflow commands treat
#: specially — including a carriage return (``\r`` → ``%0D``), a newline, ``%``,
#: ``::``, ``:``, and ``,`` — so escaping of each is exercised.
_HOSTILE = "ev%il\r\nname::error title=Fake::x:,y"


def _hostile_scorecard() -> Scorecard:
    payload = VerdictPayload(
        verdict=Verdict.INFORMATIONAL,
        ci_should_fail=False,
        informational_metrics=[_HOSTILE],
    )
    metric = AggregatedMetric(
        metric=_HOSTILE,
        aggregation=Aggregation.MEAN,
        value=1.0,
        included_count=1,
        status_counts={"scored": 1},
    )
    authority = {
        _HOSTILE: ResolvedAuthority(
            can_gate=False, level=AuthorityLevel.INFORMATIONAL, blocked=False, reasons=["why"]
        )
    }
    diagnostic = Diagnostic(code="d::code", severity=Severity.WARNING, message="msg\nwith:newline")
    return Scorecard(
        verdict=payload, metrics=[metric], authority=authority, diagnostics=[diagnostic]
    )


@pytest.mark.public_surface
def test_ci_annotation_format_frozen(tmp_path: Path) -> None:
    text = CiAnnotationSink().render(informational_scorecard(tmp_path))
    assert text == (_SNAP / "ci_annotations.txt").read_text(encoding="utf-8")


@pytest.mark.public_surface
def test_ci_annotation_injection_escaped() -> None:
    sc = _hostile_scorecard()
    text = CiAnnotationSink().render(sc)
    # The raw hostile string never appears verbatim; its specials are escaped.
    assert _HOSTILE not in text
    # %0D = carriage return, %0A = newline, %25 = %, %3A = ':', %2C = ','.
    for escaped in ("%0D", "%0A", "%25", "%3A", "%2C"):
        assert escaped in text
    # No literal CR/LF survived to split the output into a forged command.
    assert "\r" not in text.replace("\n", "")
    # No forged extra command: exactly headline + one per metric + one per diagnostic.
    assert ci_command_count(text) == len(sc.metrics) + len(sc.diagnostics) + 1


@pytest.mark.public_surface
def test_ci_clean_run_emits_no_error(tmp_path: Path) -> None:
    text = CiAnnotationSink().render(informational_scorecard(tmp_path))
    assert "::error" not in text
