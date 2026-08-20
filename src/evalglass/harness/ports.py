"""Runtime Harness ports — the effectful seams the core never imports (EG-M1-2+).

A *port* is a ``typing.Protocol`` the harness depends on; concrete adapters live in
:mod:`evalglass.adapters`. The Evaluation Core must never import this module — it owns
effects, not meaning (CLAUDE.md §4/§12; enforced by ``tools/check_core_isolation.py``).

M1 defines :class:`DatasetStore` now; ``TraceSource``, ``ResultStore``, and ``ScoreSink``
follow in later M1 slices, and ``TaskRunner`` (M2) / ``JudgeModel`` (M4) attach through the
same pattern. Adapters return *evidence and data*, never scores, authority, or verdicts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from evalglass.core import (
    DataPolicy,
    DatasetStatus,
    Diagnostic,
    EvalUnit,
    Example,
    JudgeEvidenceStatus,
    RunRecord,
    Scorecard,
    TraceEnvelope,
)
from evalglass.core.authority import JudgeCapability
from evalglass.harness.coverage import SourceImportManifest


@dataclass(frozen=True)
class DatasetRead:
    """The result of reading one dataset: its examples plus host-declared metadata.

    ``status``/``version``/``data_policy`` are sourced from host-owned config and passed
    through unchanged — the adapter never infers or upgrades them. Malformed records become
    ``diagnostics`` rather than dropping silently or becoming a score. ``manifest`` (B2) is the
    additive per-source coverage account; a pre-B2 adapter that leaves it ``None`` is unchanged.
    """

    name: str
    status: DatasetStatus
    version: str
    data_policy: DataPolicy
    examples: list[Example]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    manifest: SourceImportManifest | None = None


@runtime_checkable
class DatasetStore(Protocol):
    """Reads examples, references, dataset status, and dataset version (build contract §8)."""

    def read(self) -> DatasetRead: ...


@dataclass(frozen=True)
class TraceUnit:
    """One normalized slice of recorded behavior: a vendor-neutral envelope + its unit."""

    envelope: TraceEnvelope
    unit: EvalUnit


@dataclass(frozen=True)
class TraceRead:
    """The result of reading one trace source: normalized units plus diagnostics.

    Only ``TraceEnvelope``/``EvalUnit`` cross this boundary — a raw or vendor-specific trace
    shape must never reach the evaluator-visible path (build contract §6 trace rule).
    """

    name: str
    data_policy: DataPolicy
    units: list[TraceUnit]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    manifest: SourceImportManifest | None = None


@runtime_checkable
class TraceSource(Protocol):
    """Yields recorded host behavior, normalized to ``TraceEnvelope`` (build contract §8)."""

    def read(self) -> TraceRead: ...


@dataclass(frozen=True)
class ResultPaths:
    """Where a run's persisted typed artifacts live."""

    run_dir: Path
    runrecord: Path
    scorecard: Path


@runtime_checkable
class ResultStore(Protocol):
    """Persists the primary machine artifacts (RunRecord, Scorecard) — never mutates them."""

    def persist(self, record: RunRecord) -> ResultPaths: ...


@runtime_checkable
class ScoreSink(Protocol):
    """Renders an immutable ``Scorecard`` to text — never recomputes verdict or authority."""

    def render(self, scorecard: Scorecard) -> str: ...


@dataclass(frozen=True)
class TaskRequest:
    """One host-replay request: the example to produce output for, plus its input."""

    example_id: str
    input: Any


@dataclass(frozen=True)
class TaskResult:
    """The outcome of one replay: a parsed ``output`` or ``None`` plus typed diagnostics.

    A failed replay carries ``output=None`` and ``diagnostics`` — typed *infrastructure*
    evidence (timeout, non-zero exit, malformed output), never a score (build contract §8).
    """

    example_id: str
    output: Any | None
    diagnostics: list[Diagnostic] = field(default_factory=list)


@runtime_checkable
class TaskRunner(Protocol):
    """Runs the host system to collect fresh output when an example lacks it (build contract §8).

    Returns evidence/data only — never a score, authority, or verdict. The MVP adapter is a
    subprocess JSON in/out runner; failures become :class:`TaskResult` diagnostics.
    """

    def run(self, request: TaskRequest) -> TaskResult: ...


@dataclass(frozen=True)
class JudgeRequest:
    """One judge invocation request: the example to judge for a metric, plus refs.

    The harness gathers this and hands it to a :class:`JudgeModel` adapter. ``context`` is
    the example's host-supplied context/metadata; rubric/prompt/model refs are filled from
    host-owned config in EG-M4-2. The adapter returns evidence, never a score.
    """

    example_id: str
    metric: str
    input: Any
    output: Any
    reference: Any | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    rubric_ref: str | None = None
    prompt_ref: str | None = None
    model_ref: str | None = None


@dataclass(frozen=True)
class JudgeResult:
    """A judge adapter's outcome for one request — *evidence, not authority*.

    A non-``OK`` status (timeout / provider error / malformed / missing response) carries no
    ``parsed_value`` and typed ``diagnostics``: a failed judge is not a low score (build
    contract §6/§9). The harness maps this into a core ``JudgeEvidence``.
    """

    example_id: str
    metric: str
    status: JudgeEvidenceStatus
    parsed_value: float | None = None
    raw_response: str | None = None
    rationale: str | None = None
    tokens: int | None = None
    cost: float | None = None
    latency_ms: float | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    #: Structured judge output (ADR 0053), present only for an ``OK`` structured rubric:
    #: per-criterion facet values, rule violations, and cited (dossier-resolved) evidence refs.
    #: ``refusal_reason`` accompanies a judge that declined to score (a ``MISSING`` status).
    facets: dict[str, float | bool | str] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    refusal_reason: str | None = None


@runtime_checkable
class JudgeModel(Protocol):
    """Collects judge evidence for a metric that declares it (build contract §8; EG-M4-1).

    Returns evidence/data only — never a score, authority, or verdict. The required tier uses
    a fake deterministic adapter (no network, no provider SDK); a minimal live provider lane
    attaches through this same port in EG-M4-5.

    ``capability`` declares *what kind of instrument* the adapter is (EG-NR-1): a real
    ``MEASUREMENT`` judge may earn gating authority once calibrated, a ``SYNTHETIC_TEST_DOUBLE``
    (the fake) can never gate. The harness reads this from the adapter — not from a config name —
    and threads it into authority resolution, so no calibration/approval can turn a synthetic
    double into a measurement.
    """

    capability: JudgeCapability

    def judge(self, request: JudgeRequest) -> JudgeResult: ...
