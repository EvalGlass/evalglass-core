"""Exit-class taxonomy derived from the core verdict only (EG-M2-3).

The process exit class is a fixed lookup over the product :class:`~evalglass.core.VerdictPayload`
— ``pass``/``informational`` exit zero, ``fail``/``blocked`` exit nonzero (quality) — plus one
distinct class for an **infrastructure/setup** failure (exit 2) that occurs *before* a core
verdict exists. The harness never computes its own verdict or exit logic; it maps the verdict the
core already emitted (build contract §8; ADR 0008). Stdlib-only, effect-free.
"""

from __future__ import annotations

import enum

from evalglass.core import Scorecard, Verdict


class ExitClass(enum.StrEnum):
    """The process outcome class. ``infrastructure_error`` is never a quality verdict."""

    ZERO = "zero"
    NONZERO_FAIL = "nonzero_fail"
    NONZERO_BLOCKED = "nonzero_blocked"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


# A fixed lookup over the *product* verdict — never a recomputation of it. Infrastructure errors
# have no Scorecard, so they are not derivable here; the CLI uses INFRASTRUCTURE_ERROR directly
# on its setup/infra path.
_VERDICT_CLASS: dict[Verdict, ExitClass] = {
    Verdict.INFORMATIONAL: ExitClass.ZERO,
    Verdict.PASS: ExitClass.ZERO,
    Verdict.FAIL: ExitClass.NONZERO_FAIL,
    Verdict.BLOCKED: ExitClass.NONZERO_BLOCKED,
}

_EXIT_CODE: dict[ExitClass, int] = {
    ExitClass.ZERO: 0,
    ExitClass.NONZERO_FAIL: 1,
    ExitClass.NONZERO_BLOCKED: 1,
    ExitClass.INFRASTRUCTURE_ERROR: 2,
}


def exit_class_for(scorecard: Scorecard) -> ExitClass:
    """The exit class implied by a run's verdict (the only source — never recomputed)."""
    return _VERDICT_CLASS[scorecard.verdict.verdict]


def exit_code(klass: ExitClass) -> int:
    """The process exit code for an exit class: 0 quality-ok · 1 quality-fail/blocked · 2 infra."""
    return _EXIT_CODE[klass]
