"""Source import coverage manifests (Epic B, B2).

Every source a run reads — a local dataset, a local trace export, or a live connector lane —
produces exactly one typed :class:`SourceImportManifest`: a provider-neutral account of what the
source returned and what EvalGlass accepted, rejected, fell back on, or lost. Its purpose is a
single one: **an empty or partial import must never look like complete behavioral evidence.**

A manifest is *evidence*, never authority. It informs evaluability and diagnostics and is persisted
as a RunRecord side channel, but it never grants gating authority, never computes a quality score,
and never enters a verdict — exactly like ``lane_results``. Completeness is a typed state
(:class:`SourceCompleteness`), so a renderer cannot label a partial import "complete".

Stdlib + core only (``Diagnostic``/``DataPolicy``); it imports no port or adapter, so ``ports.py``
can annotate ``TraceRead``/``DatasetRead`` with a manifest without an import cycle.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core import DataPolicy, Diagnostic

#: Vendor-neutral marker a connector stamps as a top-level *span* key (NOT in ``attributes`` or
#: ``_eg_metadata``, so ``map_span`` ignores it and it never reaches evaluator-visible metadata)
#: when a span is a trace-level fallback rather than hydrated observation-level evidence. The
#: coverage boundary counts these from the pre-normalization span list so a fallback is visible.
TRACE_LEVEL_FALLBACK_SPAN_KEY = "_eg_trace_level_fallback"

#: The behavior/evidence layers a manifest reports availability for (order is stable for output).
AVAILABILITY_LAYERS: tuple[str, ...] = (
    "input",
    "application_output",
    "raw_model_output",
    "parser_diagnostics",
    "hierarchy",
    "tool_calls",
    "model_settings",
    "usage",
    "stable_ids",
)


class SourceCompleteness(enum.StrEnum):
    """Typed completeness of one source import — never a percentage, never a score."""

    #: Every seen record was accepted and emitted within the source's declared scope.
    COMPLETE = "complete_within_declared_scope"
    #: Some records were rejected, fell back to a coarser layer, or were not emitted.
    PARTIAL = "partial"
    #: The source was reachable and valid but returned nothing (an empty-valid response).
    EMPTY = "empty"
    #: The source never yielded evidence — egress refused, a missing prerequisite, or unreachable.
    BLOCKED = "blocked"


def derive_completeness(
    *,
    records_seen: int,
    units_emitted: int,
    rejected: int,
    trace_level_fallback: int = 0,
    blocked: bool = False,
) -> SourceCompleteness:
    """Classify a source read from its reconciled counts (fail-safe toward the weaker claim).

    ``blocked`` (egress refused / missing prerequisite) wins outright. A read that saw and emitted
    nothing is ``empty`` (an empty-valid response is never ``complete``). Any rejected record, any
    trace-level fallback, or any seen-but-not-emitted record is ``partial``. Only a read where every
    seen record was emitted at full fidelity is ``complete_within_declared_scope``.
    """
    if blocked:
        return SourceCompleteness.BLOCKED
    if records_seen == 0 and units_emitted == 0 and rejected == 0:
        return SourceCompleteness.EMPTY
    if rejected > 0 or trace_level_fallback > 0 or units_emitted < records_seen:
        return SourceCompleteness.PARTIAL
    return SourceCompleteness.COMPLETE


@dataclass(frozen=True)
class SourceImportManifest:
    """A provider-neutral account of one source import: identity, reconciled counts, completeness.

    Counts reconcile as ``records_seen == units_emitted + rejected`` for record-oriented sources;
    ``trace_level_fallback`` counts emitted units that fell back to a coarser (trace-level) layer
    instead of hydrated observation-level evidence, so a fallback is visible rather than passing as
    full-fidelity evidence. ``availability`` reports which behavior layers were present. No vendor
    object, raw payload, or secret is retained — only safe, stable identity in ``provenance``.
    """

    source: str
    kind: str
    adapter: str
    data_policy: DataPolicy
    completeness: SourceCompleteness
    records_seen: int
    units_emitted: int
    rejected: int = 0
    trace_level_fallback: int = 0
    duplicated: int = 0
    fmt: str | None = None
    endpoint_label: str | None = None
    availability: Mapping[str, bool] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source": self.source,
            "kind": self.kind,
            "adapter": self.adapter,
            "data_policy": self.data_policy.value,
            "completeness": self.completeness.value,
            "records_seen": self.records_seen,
            "units_emitted": self.units_emitted,
            "rejected": self.rejected,
            "trace_level_fallback": self.trace_level_fallback,
            "duplicated": self.duplicated,
            "availability": {k: bool(v) for k, v in self.availability.items()},
        }
        if self.fmt is not None:
            out["fmt"] = self.fmt
        if self.endpoint_label is not None:
            out["endpoint_label"] = self.endpoint_label
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        return out

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        # A uniform ValueError contract: every malformed manifest (wrong type or bad field) raises
        # ValueError so a single ``except ValueError`` at the read boundary catches all of them.
        if not isinstance(data, Mapping):
            raise ValueError(  # noqa: TRY004 — uniform ValueError contract (see above)
                f"source manifest must be a mapping, got {type(data).__name__}"
            )
        try:
            return cls(
                source=str(data["source"]),
                kind=str(data["kind"]),
                adapter=str(data["adapter"]),
                data_policy=DataPolicy(data["data_policy"]),
                completeness=SourceCompleteness(data["completeness"]),
                records_seen=int(data["records_seen"]),
                units_emitted=int(data["units_emitted"]),
                rejected=int(data.get("rejected", 0)),
                trace_level_fallback=int(data.get("trace_level_fallback", 0)),
                duplicated=int(data.get("duplicated", 0)),
                fmt=_opt_str(data.get("fmt")),
                endpoint_label=_opt_str(data.get("endpoint_label")),
                availability=_availability(data.get("availability")),
                diagnostics=[Diagnostic.from_dict(d) for d in data.get("diagnostics", [])],
                provenance=dict(data.get("provenance", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid source manifest: {exc}") from exc


def _opt_str(value: Any) -> str | None:
    """``None`` stays ``None``; anything else is coerced to ``str`` (manifest field parsing)."""
    return None if value is None else str(value)


def _availability(raw: Any) -> dict[str, bool]:
    """Coerce a serialized availability mapping to ``{str: bool}`` (absent → empty)."""
    return {str(k): bool(v) for k, v in dict(raw or {}).items()}


def availability_from_behaviors(behaviors: list[Mapping[str, Any]]) -> dict[str, bool]:
    """Report which behavior layers appear across emitted units (all False when none emitted)."""
    present = dict.fromkeys(AVAILABILITY_LAYERS, False)
    for behavior in behaviors:
        if "input" in behavior:
            present["input"] = True
        if behavior.get("output") is not None:
            present["application_output"] = True
        if behavior.get("raw_output") is not None or behavior.get("raw_model_output") is not None:
            present["raw_model_output"] = True
        if behavior.get("parser_diagnostics"):
            present["parser_diagnostics"] = True
        if behavior.get("children") or behavior.get("observations"):
            present["hierarchy"] = True
        if behavior.get("tool_calls"):
            present["tool_calls"] = True
        if behavior.get("model") is not None:
            present["model_settings"] = True
        if behavior.get("usage"):
            present["usage"] = True
    return present
