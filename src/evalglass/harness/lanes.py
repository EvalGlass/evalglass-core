"""Extension-lane framework (EG-M5-1; ADR 0017).

An *extension lane* is opt-in, deletable evidence plumbing that attaches to the runtime through
an **existing port** — never a required dependency and never an authority. This module is the
required-tier-safe framework: it declares lane **metadata** (:class:`ExtensionLane`), the lane
**result** shape (:class:`LaneResult`), and a metadata-only :class:`LaneRegistry` that lists
declared lanes **without importing any concrete lane module**. The concrete lane is imported only
on demand, by :meth:`LaneRegistry.resolve`.

Rules (CLAUDE.md §14/§19; build contract §6/§8):

- **No required path imports a concrete lane.** The registry holds metadata (a dotted ``module``
  string) and resolves the lane's factory lazily via :func:`importlib.import_module`. Removing a
  lane file therefore leaves the required suite green (the import-boundary guard in
  ``tests/core_isolation/test_lane_boundary.py`` proves it).
- **A lane declares** ``purpose``, the ``port`` it attaches to, its ``module``/``factory``, optional
  dependencies (pinned extras), prerequisites, a ``boundary`` statement, and a ``deletion_rule``.
- **A missing prerequisite skips/blocks clearly** (:class:`MissingPrerequisite`) — it never fails a
  required path.
- **A lane grants no authority.** It yields a :class:`LaneResult` (``ran``/``skipped``/``blocked`` +
  diagnostics + a reviewable report) — never a ``Score``, authority, or verdict.

This module imports only the standard library and the effect-free core (for :class:`Diagnostic`).
It must never import :mod:`evalglass.adapters` lane modules or any provider SDK.
"""

from __future__ import annotations

import enum
import importlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from evalglass.core import Diagnostic


class LaneError(ValueError):
    """A lane declaration or registry is structurally invalid (fail-closed)."""


class MissingPrerequisite(RuntimeError):
    """A lane's prerequisites are unavailable; the lane skips/blocks — it never fails a run.

    Distinct from :class:`LaneError` (a structural defect): a missing prerequisite is an expected,
    benign state (no endpoint, no credential) that yields a ``skipped``/``blocked`` lane result.
    """


class LanePort(enum.StrEnum):
    """The existing runtime port an extension lane attaches through (build contract §8)."""

    TRACE_SOURCE = "trace_source"
    SCORE_SINK = "score_sink"
    JUDGE_MODEL = "judge_model"
    TASK_RUNNER = "task_runner"


class LaneStatus(enum.StrEnum):
    """The outcome of attempting a lane. Never a quality verdict."""

    RAN = "ran"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class Maturity(enum.StrEnum):
    """How mature a lane is — a *capability-status* axis, never a run outcome (ADR 0029).

    This is the one place the public-site capability taxonomy (now/next/planned/experimental)
    enters the product, as additive ``ExtensionLane`` metadata. It is deliberately **not** a
    verdict, score status, or authority level: the Verdict Engine and exit mapping never read it
    (FS-ISO-3). A lane that forgets to declare its maturity defaults to the *conservative* end
    (``experimental``), so missing metadata can never read as "shipped".
    """

    NOW = "now"
    NEXT = "next"
    PLANNED = "planned"
    EXPERIMENTAL = "experimental"


_REQUIRED_STR_FIELDS = ("name", "purpose", "module", "factory", "boundary", "deletion_rule")


@dataclass(frozen=True)
class ExtensionLane:
    """Declared metadata for one optional extension lane (JSON-compatible, fail-closed).

    ``module``/``factory`` are a *dotted path string* and a callable name — metadata only; the
    framework never imports them (only :meth:`LaneRegistry.resolve` does, on demand). ``boundary``
    states what stays isolated; ``deletion_rule`` states what removing the lane leaves intact.
    """

    name: str
    purpose: str
    port: LanePort
    module: str
    factory: str
    boundary: str
    deletion_rule: str
    optional_dependencies: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    #: Capability status of the lane; conservative-by-default, never read by the verdict path.
    maturity: Maturity = Maturity.EXPERIMENTAL

    def __post_init__(self) -> None:
        for fld in _REQUIRED_STR_FIELDS:
            value = getattr(self, fld)
            if not isinstance(value, str) or not value.strip():
                raise LaneError(f"ExtensionLane.{fld} must be a non-empty string, got {value!r}")
        if "." not in self.module:
            raise LaneError(
                f"ExtensionLane.module must be a dotted import path, got {self.module!r}"
            )
        if not isinstance(self.port, LanePort):
            raise LaneError(f"ExtensionLane.port must be a LanePort, got {self.port!r}")
        # Accept a plain string for ergonomics, but fail closed on an unknown token: a hopeful
        # ``maturity="approved"`` is a LaneError, never silently kept. Read through ``object`` so
        # a non-Maturity runtime value (the case we are guarding) is actually type-checkable.
        raw: object = self.maturity
        if not isinstance(raw, Maturity):
            if isinstance(raw, str):
                try:
                    object.__setattr__(self, "maturity", Maturity(raw))
                except ValueError:
                    allowed = ", ".join(m.value for m in Maturity)
                    raise LaneError(
                        f"ExtensionLane.maturity has unknown value {raw!r}; "
                        f"expected one of: {allowed}"
                    ) from None
            else:
                raise LaneError(f"ExtensionLane.maturity must be a Maturity, got {raw!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "port": self.port.value,
            "module": self.module,
            "factory": self.factory,
            "boundary": self.boundary,
            "deletion_rule": self.deletion_rule,
            "optional_dependencies": list(self.optional_dependencies),
            "prerequisites": list(self.prerequisites),
            "maturity": self.maturity.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExtensionLane:
        if not isinstance(data, Mapping):
            raise LaneError(f"ExtensionLane must be a mapping, got {type(data).__name__}")
        missing = [k for k in (*_REQUIRED_STR_FIELDS, "port") if k not in data]
        if missing:
            raise LaneError(f"ExtensionLane missing required field(s): {missing}")
        try:
            port = LanePort(data["port"])
        except ValueError:
            allowed = ", ".join(p.value for p in LanePort)
            raise LaneError(
                f"ExtensionLane.port has unknown value {data['port']!r}; expected one of: {allowed}"
            ) from None
        return cls(
            name=data["name"],
            purpose=data["purpose"],
            port=port,
            module=data["module"],
            factory=data["factory"],
            boundary=data["boundary"],
            deletion_rule=data["deletion_rule"],
            optional_dependencies=tuple(
                _str_tuple(data.get("optional_dependencies"), "optional_dependencies")
            ),
            prerequisites=tuple(_str_tuple(data.get("prerequisites"), "prerequisites")),
            maturity=data.get("maturity", Maturity.EXPERIMENTAL),
        )


def _str_tuple(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise LaneError(f"ExtensionLane.{key} must be a list of non-blank strings, got {value!r}")
    return tuple(value)


@dataclass(frozen=True)
class LaneResult:
    """The outcome of attaching/running a lane — *evidence, not authority*.

    Deliberately carries **no** ``score``/``verdict``/``authority`` field: a lane informs; it never
    decides. A failure or missing prerequisite is a typed :class:`Diagnostic` plus a non-``ran``
    status, never a fabricated quality value.
    """

    lane: str
    status: LaneStatus
    report: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "status": self.status.value,
            "report": self.report,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


class LaneRegistry:
    """A metadata-only registry of declared lanes; imports a lane only via :meth:`resolve`."""

    def __init__(self, lanes: tuple[ExtensionLane, ...] | list[ExtensionLane] = ()) -> None:
        self._lanes: dict[str, ExtensionLane] = {}
        for lane in lanes:
            self.register(lane)

    def register(self, lane: ExtensionLane) -> None:
        if lane.name in self._lanes:
            raise LaneError(f"duplicate lane name {lane.name!r}")
        self._lanes[lane.name] = lane

    def names(self) -> list[str]:
        return sorted(self._lanes)

    def lanes(self) -> list[ExtensionLane]:
        return [self._lanes[name] for name in self.names()]

    def get(self, name: str) -> ExtensionLane:
        if name not in self._lanes:
            raise LaneError(f"unknown lane {name!r}; known: {self.names()}")
        return self._lanes[name]

    def resolve(self, name: str) -> Any:
        """Lazily import the lane's module and return its factory callable.

        This is the **only** place a concrete lane module is imported, and it happens on demand —
        never at framework import time — so required import paths stay lane-free.
        """
        lane = self.get(name)
        try:
            module = importlib.import_module(lane.module)
        except ImportError as exc:  # an absent optional lane / missing extra — fail closed, clearly
            raise LaneError(
                f"lane {name!r} module {lane.module!r} could not be imported: {exc}"
            ) from exc
        if not hasattr(module, lane.factory):
            raise LaneError(f"lane {name!r} module {lane.module!r} has no factory {lane.factory!r}")
        return getattr(module, lane.factory)


def built_in_lanes() -> LaneRegistry:
    """The declared optional extension lanes (metadata only — no concrete lane is imported).

    M5a registers the integration lanes; each is opt-in and deletable. The live judge lane
    (EG-M4-5) is registered here as the first lane — it is the deletable-lane exemplar.
    """
    return LaneRegistry(
        [
            ExtensionLane(
                name="live-judge",
                purpose="Call a host HTTPS judge endpoint to collect judge evidence.",
                port=LanePort.JUDGE_MODEL,
                module="evalglass.adapters.judge_live",
                factory="LiveJudgeModel",
                boundary="Judge calls occur only in this lane; the required tier uses the fake "
                "adapter and stays hermetic (no network, no provider SDK).",
                deletion_rule="Deleting adapters/judge_live.py leaves the required judge suite "
                "green (the fake adapter is the only required-tier judge).",
                optional_dependencies=(),  # stdlib urllib only; ships no provider SDK
                prerequisites=("a host-configured HTTPS judge endpoint",),
            ),
            ExtensionLane(
                name="trace-backend",
                purpose="Read recorded spans from a tracing backend and normalize them to "
                "TraceEnvelope (stub backend; a real SDK adapter replaces the read).",
                port=LanePort.TRACE_SOURCE,
                module="evalglass.adapters.trace_backend_stub",
                factory="StubBackendTraceSource",
                boundary="Vendor spans are normalized to TraceEnvelope at the lane boundary; no "
                "vendor object reaches the core, evaluators, RunRecord, or Scorecard.",
                deletion_rule="Deleting adapters/trace_backend_stub.py leaves the local JSONL "
                "trace route intact (the required tier imports no backend lane).",
                optional_dependencies=(),  # stub: stdlib only; a real backend adds a pinned extra
                prerequisites=("a configured trace backend (query/endpoint)",),
            ),
            ExtensionLane(
                name="score-sink-export",
                purpose="Publish an immutable Scorecard to an external destination (stub: a local "
                "export dir; a real backend uploader replaces the write).",
                port=LanePort.SCORE_SINK,
                module="evalglass.adapters.score_sink_export",
                factory="FileScorecardExportSink",
                boundary="The sink consumes the Scorecard read-only; it cannot mutate the verdict, "
                "authority, or CI exit — a failed publish is a diagnostic, not a changed verdict.",
                deletion_rule="Deleting adapters/score_sink_export.py leaves the local JSON + "
                "Markdown reports intact (the required tier imports no export lane).",
                optional_dependencies=(),  # stub: stdlib only; a real uploader adds a pinned extra
                prerequisites=("a configured export destination",),
            ),
            ExtensionLane(
                name="hosted-dashboard",
                purpose="Publish an immutable Scorecard to a hosted dashboard endpoint as a "
                "one-way export (dependency-injected transport; stdlib urllib by default).",
                port=LanePort.SCORE_SINK,
                module="evalglass.adapters.score_sink_dashboard",
                factory="DashboardScoreSink",
                boundary="The sink consumes the Scorecard read-only and checks data policy before "
                "any egress; it cannot mutate the verdict, authority, or CI exit — a forbidden "
                "policy or failed publish is a diagnostic, never a changed verdict.",
                deletion_rule="Deleting adapters/score_sink_dashboard.py leaves the local JSON + "
                "Markdown reports intact (the required tier imports no dashboard lane).",
                optional_dependencies=(),  # stdlib urllib only; ships no provider/HTTP SDK
                prerequisites=("a configured hosted-dashboard endpoint",),
                maturity=Maturity.NEXT,
            ),
            ExtensionLane(
                name="optimizer-handoff",
                purpose="Write a one-way, Scorecard-derived findings artifact under "
                "reports/optimizer/ for an external prompt optimizer (write-only; no return path).",
                port=LanePort.SCORE_SINK,
                module="evalglass.adapters.optimizer_handoff",
                factory="OptimizerHandoffSink",
                boundary="The handoff consumes the Scorecard read-only, echoes the verdict "
                "verbatim, and writes only under reports/optimizer/; it never writes back into "
                "datasets, evaluators, rubrics, config, baselines, or authority, and recomputes "
                "no meaning.",
                deletion_rule="Deleting adapters/optimizer_handoff.py leaves the local JSON + "
                "Markdown reports intact (the required tier imports no handoff lane).",
                optional_dependencies=(),  # stdlib only; ships no optimizer SDK
                prerequisites=(),  # writes locally under the run's reports dir — always available
                maturity=Maturity.NEXT,
            ),
            ExtensionLane(
                name="async-observation",
                purpose="Observe recorded async (interleaved) behavior and normalize it to "
                "TraceEnvelope — observation only, never orchestration.",
                port=LanePort.TRACE_SOURCE,
                module="evalglass.adapters.async_observation",
                factory="AsyncObservationTraceSource",
                boundary="Reads a recorded file only; it never runs/orchestrates the host. Async "
                "metadata is recorded fact, not an orchestration handle; the core sees only the "
                "normalized TraceEnvelope.",
                deletion_rule="Deleting adapters/async_observation.py leaves the local JSONL trace "
                "route intact (the required tier imports no async lane).",
                optional_dependencies=(),  # stdlib only
                prerequisites=("a recorded async trace file",),
            ),
            ExtensionLane(
                name="langfuse-trace",
                purpose="Import recorded traces from a Langfuse instance and normalize them to "
                "TraceEnvelope (opt-in connector; the SDK is imported lazily inside the lane).",
                port=LanePort.TRACE_SOURCE,
                module="evalglass.adapters.trace_langfuse",
                factory="LangfuseTraceSource",
                boundary="Langfuse traces are normalized to TraceEnvelope at the lane boundary; no "
                "Langfuse object reaches the core, evaluators, RunRecord, or Scorecard, and the "
                "SDK is imported lazily inside the lane (never on a required import path).",
                deletion_rule="Deleting adapters/trace_langfuse.py leaves the required, hermetic "
                "tier and the local JSONL trace route intact (the required tier imports no "
                "connector).",
                optional_dependencies=("langfuse-trace",),  # pinned optional extra (langfuse SDK)
                prerequisites=("a configured Langfuse host/endpoint and API credentials",),
                maturity=Maturity.PLANNED,
            ),
            ExtensionLane(
                name="phoenix-trace",
                purpose="Import recorded spans from an Arize Phoenix instance and normalize them "
                "to TraceEnvelope (opt-in connector; the SDK is imported lazily inside the lane).",
                port=LanePort.TRACE_SOURCE,
                module="evalglass.adapters.trace_phoenix",
                factory="PhoenixTraceSource",
                boundary="Phoenix spans are normalized to TraceEnvelope at the lane boundary; no "
                "Phoenix object reaches the core, evaluators, RunRecord, or Scorecard, and the "
                "SDK (arize-phoenix-client) is imported lazily inside the lane.",
                deletion_rule="Deleting adapters/trace_phoenix.py leaves the required, hermetic "
                "tier and the local JSONL trace route intact (the required tier imports no "
                "connector).",
                optional_dependencies=(
                    "phoenix-trace",
                ),  # pinned optional extra (arize-phoenix-client)
                prerequisites=("a configured Phoenix collector endpoint and API credentials",),
                maturity=Maturity.PLANNED,
            ),
            ExtensionLane(
                name="langsmith-trace",
                purpose="Import recorded runs from a LangSmith instance and normalize them to "
                "TraceEnvelope (opt-in connector; the SDK is imported lazily inside the lane).",
                port=LanePort.TRACE_SOURCE,
                module="evalglass.adapters.trace_langsmith",
                factory="LangSmithTraceSource",
                boundary="LangSmith runs are normalized to TraceEnvelope at the lane boundary; no "
                "LangSmith object reaches the core, evaluators, RunRecord, or Scorecard, and the "
                "SDK (langsmith, never LangChain) is imported lazily inside the lane.",
                deletion_rule="Deleting adapters/trace_langsmith.py leaves the required, hermetic "
                "tier and the local JSONL trace route intact (the required tier imports no "
                "connector).",
                optional_dependencies=("langsmith-trace",),  # pinned optional extra (langsmith SDK)
                prerequisites=("a configured LangSmith API endpoint and API credentials",),
                maturity=Maturity.PLANNED,
            ),
        ]
    )
