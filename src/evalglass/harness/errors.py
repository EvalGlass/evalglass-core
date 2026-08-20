"""Setup-phase errors for the Runtime Harness (EG-M1-1).

A configuration, loading, or input problem detected *before* the Evaluation Core
runs is a **setup error**, not a host quality failure (build contract §8;
architecture.md §3). It is carried as a typed :class:`~evalglass.core.Diagnostic`
and mapped to a distinct exit class by the CLI — never reported as a low score or
a fabricated verdict, and never surfaced as a raw traceback.
"""

from __future__ import annotations

from evalglass.core import Diagnostic, Severity


class SetupError(Exception):
    """A harness setup failure carrying the structured diagnostic to report."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def setup_diagnostic(
    code: str,
    message: str,
    *,
    location: str | None = None,
    cause: str | None = None,
) -> Diagnostic:
    """Build an ``ERROR``-severity setup diagnostic."""
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        location=location,
        cause=cause,
    )
