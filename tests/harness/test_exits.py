"""Exit-class taxonomy derived from the core verdict only (EG-M2-3).

The process exit class is a fixed lookup over the product ``VerdictPayload`` — pass/
informational exit zero, fail/blocked exit nonzero (quality), and an infrastructure/setup
failure is its own class (exit 2), never collapsed into the quality class (build contract §8;
ADR 0008). The harness must not compute its own exit logic.
"""

from __future__ import annotations

import pytest

from evalglass.core import Scorecard, Verdict, VerdictPayload
from evalglass.harness.exits import ExitClass, exit_class_for, exit_code


def _scorecard(payload: VerdictPayload) -> Scorecard:
    return Scorecard(verdict=payload, metrics=[], authority={})


def _payload(verdict: Verdict) -> VerdictPayload:
    if verdict is Verdict.FAIL:
        return VerdictPayload(verdict, ci_should_fail=True, failing_gates=["m"])
    if verdict is Verdict.BLOCKED:
        return VerdictPayload(verdict, ci_should_fail=True, blocked_gates=["m"])
    if verdict is Verdict.PASS:
        return VerdictPayload(verdict, ci_should_fail=False, passing_gates=["m"])
    return VerdictPayload(verdict, ci_should_fail=False, informational_metrics=["m"])


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (Verdict.INFORMATIONAL, ExitClass.ZERO),
        (Verdict.PASS, ExitClass.ZERO),
        (Verdict.FAIL, ExitClass.NONZERO_FAIL),
        (Verdict.BLOCKED, ExitClass.NONZERO_BLOCKED),
    ],
)
def test_exit_class_for_each_verdict(verdict: Verdict, expected: ExitClass) -> None:
    assert exit_class_for(_scorecard(_payload(verdict))) is expected


@pytest.mark.parametrize(
    ("klass", "code"),
    [
        (ExitClass.ZERO, 0),
        (ExitClass.NONZERO_FAIL, 1),
        (ExitClass.NONZERO_BLOCKED, 1),
        (ExitClass.INFRASTRUCTURE_ERROR, 2),
    ],
)
def test_exit_code_mapping(klass: ExitClass, code: int) -> None:
    assert exit_code(klass) == code


def test_exit_class_tracks_ci_should_fail() -> None:
    # zero exit classes never set ci_should_fail; nonzero ones always do — the same structural
    # consistency the product guarantees, re-derived from the payload (never recomputed).
    for verdict in Verdict:
        sc = _scorecard(_payload(verdict))
        klass = exit_class_for(sc)
        assert (exit_code(klass) != 0) == sc.verdict.ci_should_fail
