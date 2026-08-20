"""Public input/data contracts for the Evaluation Core (EG-M0-1a).

These are the JSON-compatible boundary types the whole system shares: the
trace -> unit -> example route plus evidence and diagnostics. They are *meaning*,
not effects — this module is part of the effect-free Evaluation Core and imports
only the standard library (``CLAUDE.md §8``; enforced by
``tools/check_core_isolation.py``).

Every contract exposes ``to_dict()`` (plain JSON-compatible data; enums become
their string values) and a fail-closed ``from_dict()`` classmethod that rejects
missing or malformed fields with :class:`ContractError` rather than silently
coercing them. The measurement/output contracts (MetricSpec, Score, RunRecord,
Scorecard, ...) land in EG-M0-1b alongside this module.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any, Self

from evalglass.core._validation import ContractError as ContractError  # re-exported
from evalglass.core._validation import (
    _as_finite_float,
    _as_int,
    _as_mapping,
    _coerce_enum,
    _opt_float,
    _opt_int,
    _opt_list,
    _opt_mapping,
    _opt_str,
    _opt_str_list,
    _require,
    _require_mapping,
    _require_str,
)


class Severity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DataPolicy(enum.StrEnum):
    PERMITTED = "permitted"
    REDACTED = "redacted"
    FORBIDDEN = "forbidden"
    MISSING = "missing"
    UNKNOWN = "unknown"


class UnitKind(enum.StrEnum):
    """The slice of behavior a unit selects. MVP scores ``CALL``; the rest are reserved."""

    CALL = "call"
    STEP = "step"
    TRAJECTORY = "trajectory"
    SESSION = "session"


class JudgeEvidenceStatus(enum.StrEnum):
    """Whether the Runtime Harness obtained a usable judge response.

    A non-``OK`` status is an effect-edge outcome (timeout, provider error, no or
    garbled response), not a low score: only ``OK`` evidence may carry a parsed
    value (mirrors the cardinal ``Score`` rule — ``CLAUDE.md §9/§14``).
    """

    OK = "ok"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    MALFORMED = "malformed"
    MISSING = "missing"


# --- contracts --------------------------------------------------------------


@dataclass(frozen=True)
class Diagnostic:
    """A structured explanation for a non-perfect or non-measured outcome."""

    code: str
    severity: Severity
    message: str
    location: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    cause: str | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.location is not None:
            out["location"] = self.location
        if self.details:
            out["details"] = dict(self.details)
        if self.cause is not None:
            out["cause"] = self.cause
        if self.evidence_refs:
            out["evidence_refs"] = list(self.evidence_refs)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Diagnostic")
        severity = _require(m, "severity", "Diagnostic")
        return cls(
            code=_require_str(m, "code", "Diagnostic"),
            severity=_coerce_enum(Severity, severity, "severity", "Diagnostic"),
            message=_require_str(m, "message", "Diagnostic"),
            location=_opt_str(m, "location", "Diagnostic"),
            details=_opt_mapping(m, "details", "Diagnostic"),
            cause=_opt_str(m, "cause", "Diagnostic"),
            evidence_refs=_opt_str_list(m, "evidence_refs", "Diagnostic"),
        )


@dataclass(frozen=True)
class TraceEnvelope:
    """Vendor-neutral normalized host behavior. The core never sees vendor trace shapes."""

    trace_id: str
    source: str
    behavior: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    data_policy: DataPolicy = DataPolicy.UNKNOWN
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "trace_id": self.trace_id,
            "source": self.source,
            "behavior": dict(self.behavior),
            "data_policy": self.data_policy.value,
        }
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "TraceEnvelope")
        # data_policy is required at the parse boundary: an adapter that omits a
        # policy decision must fail closed rather than be silently read as UNKNOWN,
        # which would erase the distinct MISSING/UNKNOWN states authority depends on.
        # (The dataclass keeps an UNKNOWN default only for internal construction.)
        policy = _require(m, "data_policy", "TraceEnvelope")
        return cls(
            trace_id=_require_str(m, "trace_id", "TraceEnvelope"),
            source=_require_str(m, "source", "TraceEnvelope"),
            behavior=_require_mapping(m, "behavior", "TraceEnvelope"),
            metadata=_opt_mapping(m, "metadata", "TraceEnvelope"),
            data_policy=_coerce_enum(DataPolicy, policy, "data_policy", "TraceEnvelope"),
            provenance=_opt_mapping(m, "provenance", "TraceEnvelope"),
        )


@dataclass(frozen=True)
class EvalUnit:
    """A declared slice of behavior to evaluate.

    ``locator`` and ``members`` are reserved for non-call kinds (EG-M5-5; ADR 0020): a
    step/trajectory/session unit lists the sub-unit ids it aggregates over in ``members`` and may
    carry an addressing hint in ``locator``. The call-level MVP uses neither, so its serialized
    shape is unchanged and existing snapshots stay valid.
    """

    unit_id: str
    kind: UnitKind
    trace_id: str
    locator: dict[str, Any] = field(default_factory=dict)
    members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "trace_id": self.trace_id,
        }
        if self.locator:
            out["locator"] = dict(self.locator)
        if self.members:
            out["members"] = list(self.members)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "EvalUnit")
        return cls(
            unit_id=_require_str(m, "unit_id", "EvalUnit"),
            kind=_coerce_enum(UnitKind, _require(m, "kind", "EvalUnit"), "kind", "EvalUnit"),
            trace_id=_require_str(m, "trace_id", "EvalUnit"),
            locator=_opt_mapping(m, "locator", "EvalUnit"),
            members=_opt_str_list(m, "members", "EvalUnit"),
        )


@dataclass(frozen=True)
class Example:
    """An evaluator-ready item: input, output, optional reference, and its source unit."""

    example_id: str
    input: Any
    output: Any
    unit: EvalUnit
    reference: Any | None = None
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "example_id": self.example_id,
            "input": self.input,
            "output": self.output,
            "unit": self.unit.to_dict(),
        }
        if self.reference is not None:
            out["reference"] = self.reference
        if self.context:
            out["context"] = dict(self.context)
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Example")
        return cls(
            example_id=_require_str(m, "example_id", "Example"),
            input=_require(m, "input", "Example"),
            output=_require(m, "output", "Example"),
            unit=EvalUnit.from_dict(_require_mapping(m, "unit", "Example")),
            reference=m.get("reference"),
            context=_opt_mapping(m, "context", "Example"),
            metadata=_opt_mapping(m, "metadata", "Example"),
            provenance=_opt_mapping(m, "provenance", "Example"),
        )


def _parse_facets_mapping(raw: Any) -> dict[str, float | bool | str]:
    """Parse a judge's per-criterion facet values (fail-closed): str, bool, or finite number."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ContractError("JudgeEvidence: 'facets' must be a mapping")
    out: dict[str, float | bool | str] = {}
    for name, value in raw.items():
        if not isinstance(name, str):
            raise ContractError("JudgeEvidence: facet names must be strings")
        if isinstance(value, bool | str):
            out[name] = value
        elif isinstance(value, int | float):
            out[name] = _as_finite_float(value, f"facet {name!r}", "JudgeEvidence")
        else:
            raise ContractError(
                f"JudgeEvidence: facet {name!r} must be a finite number, bool, or str"
            )
    return out


@dataclass(frozen=True)
class JudgeEvidence:
    """One judge invocation's recorded evidence — *evidence, not authority*.

    The Runtime Harness calls a ``JudgeModel`` (an effect) and records the result
    here; the effect-free judge evaluator (EG-M4-4) parses it into a ``Score``. It
    never carries a verdict or authority, and a failed call (non-``OK`` status)
    carries no ``parsed_value`` — a timed-out or unparseable judge is not a ``0.0``
    (``CLAUDE.md §9/§14``). The rubric/prompt/model/parser refs plus the response
    fingerprint feed judge provenance, so a rubric change can break baseline
    comparability (EG-M4-2).
    """

    example_id: str
    metric: str
    status: JudgeEvidenceStatus
    parsed_value: float | None = None
    raw_response: str | None = None
    rationale: str | None = None
    rubric_ref: str | None = None
    rubric_version: str | None = None
    prompt_ref: str | None = None
    model_ref: str | None = None
    parser_version: str | None = None
    response_fingerprint: str | None = None
    tokens: int | None = None
    cost: float | None = None
    latency_ms: float | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    #: Structured judge output (ADR 0053): per-criterion facet values, rule violations, and cited
    #: (dossier-resolved) evidence refs — present only for an ``OK`` structured response.
    #: ``refusal_reason`` records why a judge declined to score (a non-``OK`` status); never a
    #: value.
    facets: dict[str, float | bool | str] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    refusal_reason: str | None = None
    #: Judge-execution usage (C3; ADR 0055): the cache outcome (``hit``/``miss``) and how many
    #: retries were needed. Present only when an execution policy ran; a cache hit is visible here.
    cache_state: str | None = None
    attempts: int | None = None

    @property
    def evidence_id(self) -> str:
        """Stable id a judge ``Score.evidence_refs`` resolves to (``judge:<example>:<metric>``)."""
        return f"judge:{self.example_id}:{self.metric}"

    def without_raw_response(self) -> JudgeEvidence:
        """A copy with the raw provider text dropped (the fingerprint + parsed content remain).

        The conservative persistence default: parsed evidence and its fingerprint are portable, but
        the raw response — which may carry sensitive provider text — is retained only when the host
        opts in.
        """
        if self.raw_response is None:
            return self
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values["raw_response"] = None
        return JudgeEvidence(**values)

    def __post_init__(self) -> None:
        if self.parsed_value is not None:
            if self.status is not JudgeEvidenceStatus.OK:
                raise ContractError(
                    f"a '{self.status.value}' JudgeEvidence must not carry a parsed_value "
                    f"(got {self.parsed_value!r}); a timed-out/errored/missing/malformed judge "
                    "response is not a low score — see CLAUDE.md §9/§14"
                )
            _as_finite_float(self.parsed_value, "parsed_value", "JudgeEvidence")
        if (self.facets or self.violations or self.citations) and (
            self.status is not JudgeEvidenceStatus.OK
        ):
            raise ContractError(
                f"a '{self.status.value}' JudgeEvidence must not carry structured facets / "
                "violations / citations; structured scored content requires an 'ok' status"
            )
        # Direct construction (e.g. by the Runtime Harness) must fail closed on the same
        # numeric metadata that from_dict rejects — no parse/construct asymmetry.
        if self.cost is not None:
            _as_finite_float(self.cost, "cost", "JudgeEvidence")
        if self.latency_ms is not None:
            _as_finite_float(self.latency_ms, "latency_ms", "JudgeEvidence")
        if self.tokens is not None:
            _as_int(self.tokens, "tokens", "JudgeEvidence")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "example_id": self.example_id,
            "metric": self.metric,
            "status": self.status.value,
        }
        if self.parsed_value is not None:
            out["parsed_value"] = self.parsed_value
        for key in (
            "raw_response",
            "rationale",
            "rubric_ref",
            "rubric_version",
            "prompt_ref",
            "model_ref",
            "parser_version",
            "response_fingerprint",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.tokens is not None:
            out["tokens"] = self.tokens
        if self.cost is not None:
            out["cost"] = self.cost
        if self.latency_ms is not None:
            out["latency_ms"] = self.latency_ms
        if self.facets:
            out["facets"] = dict(self.facets)
        if self.violations:
            out["violations"] = list(self.violations)
        if self.citations:
            out["citations"] = list(self.citations)
        if self.refusal_reason is not None:
            out["refusal_reason"] = self.refusal_reason
        if self.cache_state is not None:
            out["cache_state"] = self.cache_state
        if self.attempts is not None:
            out["attempts"] = self.attempts
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        if self.provenance:
            out["provenance"] = dict(self.provenance)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "JudgeEvidence")
        return cls(
            example_id=_require_str(m, "example_id", "JudgeEvidence"),
            metric=_require_str(m, "metric", "JudgeEvidence"),
            status=_coerce_enum(
                JudgeEvidenceStatus,
                _require(m, "status", "JudgeEvidence"),
                "status",
                "JudgeEvidence",
            ),
            parsed_value=_opt_float(m, "parsed_value", "JudgeEvidence"),
            raw_response=_opt_str(m, "raw_response", "JudgeEvidence"),
            rationale=_opt_str(m, "rationale", "JudgeEvidence"),
            rubric_ref=_opt_str(m, "rubric_ref", "JudgeEvidence"),
            rubric_version=_opt_str(m, "rubric_version", "JudgeEvidence"),
            prompt_ref=_opt_str(m, "prompt_ref", "JudgeEvidence"),
            model_ref=_opt_str(m, "model_ref", "JudgeEvidence"),
            parser_version=_opt_str(m, "parser_version", "JudgeEvidence"),
            response_fingerprint=_opt_str(m, "response_fingerprint", "JudgeEvidence"),
            tokens=_opt_int(m, "tokens", "JudgeEvidence"),
            cost=_opt_float(m, "cost", "JudgeEvidence"),
            latency_ms=_opt_float(m, "latency_ms", "JudgeEvidence"),
            facets=_parse_facets_mapping(m.get("facets")),
            violations=_opt_str_list(m, "violations", "JudgeEvidence"),
            citations=_opt_str_list(m, "citations", "JudgeEvidence"),
            refusal_reason=_opt_str(m, "refusal_reason", "JudgeEvidence"),
            cache_state=_opt_str(m, "cache_state", "JudgeEvidence"),
            attempts=_opt_int(m, "attempts", "JudgeEvidence"),
            diagnostics=[
                Diagnostic.from_dict(_as_mapping(d, "JudgeEvidence.diagnostics"))
                for d in _opt_list(m, "diagnostics", "JudgeEvidence")
            ],
            provenance=_opt_mapping(m, "provenance", "JudgeEvidence"),
        )


@dataclass(frozen=True)
class EvidenceBundle:
    """Evidence the Runtime Harness collected and passes into the effect-free core."""

    references: list[Any] = field(default_factory=list)
    sources: list[Any] = field(default_factory=list)
    judge_evidence: list[JudgeEvidence] = field(default_factory=list)
    verifier_evidence: list[Any] = field(default_factory=list)
    runtime_errors: list[Diagnostic] = field(default_factory=list)
    trace_fragments: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.references:
            out["references"] = list(self.references)
        if self.sources:
            out["sources"] = list(self.sources)
        if self.judge_evidence:
            out["judge_evidence"] = [j.to_dict() for j in self.judge_evidence]
        if self.verifier_evidence:
            out["verifier_evidence"] = list(self.verifier_evidence)
        if self.runtime_errors:
            out["runtime_errors"] = [d.to_dict() for d in self.runtime_errors]
        if self.trace_fragments:
            out["trace_fragments"] = list(self.trace_fragments)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "EvidenceBundle")
        errors_raw = _opt_list(m, "runtime_errors", "EvidenceBundle")
        judge_raw = _opt_list(m, "judge_evidence", "EvidenceBundle")
        return cls(
            references=_opt_list(m, "references", "EvidenceBundle"),
            sources=_opt_list(m, "sources", "EvidenceBundle"),
            judge_evidence=[
                JudgeEvidence.from_dict(_as_mapping(j, "EvidenceBundle.judge_evidence"))
                for j in judge_raw
            ],
            verifier_evidence=_opt_list(m, "verifier_evidence", "EvidenceBundle"),
            runtime_errors=[
                Diagnostic.from_dict(_as_mapping(d, "EvidenceBundle.runtime_errors"))
                for d in errors_raw
            ],
            trace_fragments=_opt_list(m, "trace_fragments", "EvidenceBundle"),
        )
