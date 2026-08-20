"""Baseline loading (EG-M2-2a) and explicit promotion (EG-M2-2b).

A *baseline* is a previously promoted :class:`~evalglass.core.RunRecord` (ADR 0009): it carries
the prior run's provenance fingerprint, which the core uses to decide whether the current run is
*comparable* enough to support a regression claim. ``load_baseline`` returns only that
fingerprint. A configured-but-unloadable baseline (missing, unreadable, malformed, or not a
valid RunRecord) is a **setup error** — never silently treated as "no baseline", which would let
a required-baseline gate quietly downgrade. Promotion is an explicit, separate act (never during
an ordinary run); ``promote`` writes a run's record to the baseline path.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import ContractError, RunFingerprint, RunRecord
from evalglass.harness.errors import SetupError, setup_diagnostic


def load_run_record(path: Path) -> RunRecord:
    """Load and validate a persisted RunRecord (a baseline) from ``path`` (fail-closed)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SetupError(
            setup_diagnostic(
                "baseline_not_found", f"baseline file not found: {path}", location=str(path)
            )
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError — catch it here so an undecodable
        # baseline is a setup diagnostic, not a raw traceback past the CLI's handlers.
        raise SetupError(
            setup_diagnostic(
                "baseline_unreadable", f"baseline file is unreadable: {exc}", location=str(path)
            )
        ) from exc
    try:
        return RunRecord.from_dict(json.loads(text))
    except (ValueError, ContractError) as exc:
        # ContractError is a ValueError; json.JSONDecodeError is too. A corrupt baseline must
        # fail loudly, not be read as "no baseline".
        raise SetupError(
            setup_diagnostic(
                "baseline_invalid",
                f"baseline file is not a valid RunRecord: {exc}",
                location=str(path),
            )
        ) from exc


def load_baseline(path: Path) -> RunFingerprint:
    """Load a promoted baseline RunRecord and return its provenance fingerprint (fail-closed)."""
    return load_run_record(path).provenance


def promote(record: RunRecord, path: Path) -> None:
    """Write ``record`` as the baseline at ``path`` (the explicit promotion act, EG-M2-2b)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
