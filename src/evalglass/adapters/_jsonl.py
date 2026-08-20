"""Shared JSONL reading for local-file adapters (EG-M1-3b).

Both trace adapters (and any future local-file adapter) read a UTF-8 JSONL file the same
way: a missing/undecodable file is a :class:`SetupError`; blank lines are skipped; each line
is parsed with the non-standard ``NaN``/``Infinity`` tokens rejected. This module factors
that shared edge so the per-record *meaning* (each adapter's own mapping + diagnostic codes)
is all that differs. It performs only the file read; it never scores or interprets.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalglass.core import Diagnostic, Severity
from evalglass.harness.config import TraceConfig
from evalglass.harness.coverage import (
    SourceImportManifest,
    availability_from_behaviors,
    derive_completeness,
)
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.ports import TraceRead, TraceUnit


def _reject_constant(token: str) -> object:
    """Make ``json.loads`` reject the non-standard NaN/Infinity tokens it accepts by default."""
    raise ValueError(f"non-standard JSON constant {token!r}")


@dataclass(frozen=True)
class JsonLine:
    """One non-blank JSONL line: either a parsed ``record`` or a parse ``error`` message."""

    lineno: int
    record: Any
    error: str | None


def read_text(path: Path, *, not_found_code: str, unreadable_code: str, kind: str) -> str:
    """Read a UTF-8 text file, mapping every failure to a typed :class:`SetupError`."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SetupError(
            setup_diagnostic(not_found_code, f"{kind} file not found: {path}", location=str(path))
        ) from exc
    except UnicodeDecodeError as exc:
        raise SetupError(
            setup_diagnostic(
                unreadable_code, f"{kind} file is not valid UTF-8: {path}", location=str(path)
            )
        ) from exc
    except OSError as exc:
        raise SetupError(
            setup_diagnostic(
                unreadable_code, f"cannot read {kind} {path}: {exc}", location=str(path)
            )
        ) from exc


def iter_json_lines(text: str) -> Iterator[JsonLine]:
    """Yield one :class:`JsonLine` per non-blank line; a parse failure sets ``error``."""
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line, parse_constant=_reject_constant)
        except ValueError as exc:  # JSONDecodeError ⊂ ValueError; also NaN/Infinity tokens
            yield JsonLine(lineno=lineno, record=None, error=str(exc))
        else:
            yield JsonLine(lineno=lineno, record=record, error=None)


def read_trace_jsonl(
    config: TraceConfig,
    root: Path,
    mapper: Callable[[Any, int, str], TraceUnit | Diagnostic],
    *,
    adapter: str,
) -> TraceRead:
    """Drive the shared trace-JSONL read loop, delegating each record to ``mapper``.

    Both the local and open-convention TraceSources differ only in how they map one record
    to a :class:`TraceUnit`; the file read, blank-line skipping, ``trace_invalid_json``
    handling, and the coverage manifest (B2) are identical and live here. ``mapper`` returns a
    ``TraceUnit`` or a per-record ``Diagnostic``. ``adapter`` names the reader for the manifest.
    """
    path = root / config.path
    text = read_text(
        path, not_found_code="trace_not_found", unreadable_code="trace_unreadable", kind="trace"
    )
    units: list[TraceUnit] = []
    diagnostics: list[Diagnostic] = []
    records_seen = 0
    for jl in iter_json_lines(text):
        records_seen += 1
        loc = f"{config.path}:{jl.lineno}"
        if jl.error is not None:
            diagnostics.append(
                Diagnostic(
                    code="trace_invalid_json",
                    severity=Severity.ERROR,
                    message=f"invalid JSON: {jl.error}",
                    location=loc,
                )
            )
            continue
        built = mapper(jl.record, jl.lineno, loc)
        if isinstance(built, TraceUnit):
            units.append(built)
        else:
            diagnostics.append(built)
    manifest = SourceImportManifest(
        source=config.name,
        kind="trace",
        adapter=adapter,
        data_policy=config.data_policy,
        completeness=derive_completeness(
            records_seen=records_seen, units_emitted=len(units), rejected=len(diagnostics)
        ),
        records_seen=records_seen,
        units_emitted=len(units),
        rejected=len(diagnostics),
        fmt=config.fmt.value,
        availability=availability_from_behaviors([u.envelope.behavior for u in units]),
        diagnostics=list(diagnostics),
    )
    return TraceRead(
        name=config.name,
        data_policy=config.data_policy,
        units=units,
        diagnostics=diagnostics,
        manifest=manifest,
    )
