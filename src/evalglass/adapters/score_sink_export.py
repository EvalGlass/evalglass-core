"""Optional ScoreSink **export** lane (EG-M5-4; ADR 0019).

An opt-in, deletable lane that *publishes* an immutable :class:`~evalglass.core.Scorecard` to an
external destination. Following the M5a stub-first decision, the destination is a local export
directory (a stub for a backend upload / CI export); a real HTTP/backend uploader is a deletable
follow-up behind this same `export(scorecard) -> LaneResult` shape.

Invariants (build contract §6/§8/§9; ADR 0008):

- The sink **consumes** the Scorecard read-only (it only reads ``scorecard.to_dict()``); it can
  **never** mutate the verdict, authority, or CI exit.
- A sink **failure** is a typed :class:`~evalglass.harness.lanes.LaneResult` (``blocked`` + a
  :class:`~evalglass.core.Diagnostic`) — it does **not** hide or alter the core verdict.
- It is a lane: no required path imports it; deleting it leaves the local JSON + Markdown reports
  intact; an absent destination raises :class:`MissingPrerequisite` (skip). Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from evalglass.core import Diagnostic, Scorecard, Severity
from evalglass.core.contracts import DataPolicy
from evalglass.harness.lanes import LaneResult, LaneStatus, MissingPrerequisite

_EXPORT_FILENAME = "scorecard.export.json"


@runtime_checkable
class ScorecardExportSink(Protocol):
    """A lane-local export sink — distinct from the core ``ScoreSink.render`` port (no new port)."""

    def export(self, scorecard: Scorecard) -> LaneResult: ...


class FileScorecardExportSink:
    """Publish the immutable Scorecard JSON to a local export dir (a stub for a backend upload)."""

    def __init__(
        self,
        *,
        export_dir: str | None,
        root: Path,
        data_policy: str | DataPolicy = DataPolicy.UNKNOWN,
        name: str = "score-sink-export",
    ) -> None:
        if not export_dir:
            # Opt-in: with no destination configured the export lane is unavailable.
            raise MissingPrerequisite(
                "no export destination configured; the export lane is unavailable"
            )
        self._target = root / export_dir
        self._root = root
        # ``data_policy`` is the host-declared egress policy the seam threads to every SCORE_SINK
        # factory uniformly. This sink writes *locally* inside the host root (already bounded by the
        # root-escape check below), which is not egress to an external destination, so the policy
        # does not gate it; it is retained for seam symmetry and transparency.
        self._data_policy = data_policy
        self._name = name

    def export(self, scorecard: Scorecard) -> LaneResult:
        # Read-only consumption: serialize a copy of the typed Scorecard; the object is untouched.
        payload = json.dumps(scorecard.to_dict(), indent=2, sort_keys=True)
        try:
            # Fail closed if the destination escapes the host root (e.g. ``../../etc/evil``): a sink
            # publishes inside the repo, never outside it. ``resolve()`` itself can raise on a
            # symlink loop — kept inside the ``try`` so that too becomes a blocked diagnostic.
            if not self._target.resolve().is_relative_to(self._root.resolve()):
                return LaneResult(
                    lane=self._name,
                    status=LaneStatus.BLOCKED,
                    report=f"export refused: destination escapes the host root ({self._target})",
                    diagnostics=[
                        Diagnostic(
                            code="score_sink_export_outside_root",
                            severity=Severity.ERROR,
                            message=f"export destination {self._target} is outside the host root "
                            f"{self._root}; refusing to write",
                        )
                    ],
                )
            self._target.mkdir(parents=True, exist_ok=True)
            (self._target / _EXPORT_FILENAME).write_text(payload, encoding="utf-8")
        except OSError as exc:
            # A failed publish is a diagnostic — the core verdict is untouched and authoritative.
            return LaneResult(
                lane=self._name,
                status=LaneStatus.BLOCKED,
                report=f"export failed: {exc}",
                diagnostics=[
                    Diagnostic(
                        code="score_sink_export_failed",
                        severity=Severity.ERROR,
                        message=f"could not publish scorecard to {self._target}: {exc}",
                    )
                ],
            )
        return LaneResult(
            lane=self._name,
            status=LaneStatus.RAN,
            report=f"exported scorecard to {self._target / _EXPORT_FILENAME}",
        )
