"""Stable data contracts for the validator-gate skill.

Stdlib-only (dataclasses + enum + json), matching the EvalGlass "every
dependency is vendored cost" ethos and mirroring the scan-gate skill. The JSON
Schemas under ../schemas/ are the external contract; these dataclasses are the
runtime model + validation. `from_dict` tolerates unknown keys so the schema
can evolve additively.

Statuses mirror the Validator Gate architecture: PASS / PASS_WITH_WARNINGS /
BLOCKED / FAIL, with precedence **FAIL > BLOCKED > PASS_WITH_WARNINGS > PASS**
(see `worst_status`). Trust-critical missing proof is BLOCKED and is never
silently downgraded to a warning. The five canonical `FamilyId` values are a
closed set; risk-catalog references are optional metadata, never family ids.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION_EVIDENCE = "validator.evidence.v1"
SCHEMA_VERSION_RESULT = "validator.result.v1"

GATE_NAME = "validator"


class ContractError(ValueError):
    """Raised when a payload violates a contract (bad enum, missing field)."""


class Status(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class FamilyId(str, Enum):
    CONTRACT_BOUNDARY = "contract_boundary"
    AUTHORITY_VERDICT = "authority_verdict"
    EVIDENCE_PROVENANCE = "evidence_provenance"
    SCENARIO_CHECKER = "scenario_checker"
    INTEGRATION_BOUNDARY = "integration_boundary"


class Authority(str, Enum):
    PRODUCT = "product"
    EGTS = "egts"
    EXECUTION_LOOP = "execution_loop"
    SCAN_GATE = "scan_gate"
    VALIDATOR_GATE = "validator_gate"
    GENERATED_OR_PROPOSED = "generated_or_proposed"
    EXTERNAL = "external"


class ArtifactKind(str, Enum):
    RUN_RECORD = "run_record"
    SCORECARD = "scorecard"
    VERDICT = "verdict"
    DIAGNOSTIC = "diagnostic"
    REPORT = "report"
    TRACE = "trace"
    SCENARIO = "scenario"
    CHECKER_OUTPUT = "checker_output"
    BASELINE = "baseline"
    PROVENANCE = "provenance"
    AUTHORITY_RECORD = "authority_record"
    SCHEMA = "schema"
    SCAN_RESULT = "scan_result"
    REVIEW_RESULT = "review_result"


# Precedence, worst-first. The composer's single status engine uses this so the
# overall verdict is computed in exactly one place (the "one Verdict Engine"
# discipline applied to the gate itself).
STATUS_PRECEDENCE: tuple[Status, ...] = (
    Status.FAIL,
    Status.BLOCKED,
    Status.PASS_WITH_WARNINGS,
    Status.PASS,
)


def worst_status(statuses: Iterable[Status]) -> Status:
    """Return the most severe status under STATUS_PRECEDENCE; PASS if empty."""
    seen = set(statuses)
    for status in STATUS_PRECEDENCE:
        if status in seen:
            return status
    return Status.PASS


# Routing either succeeds (PASS) or refuses (BLOCKED). Semantic FAIL and
# PASS_WITH_WARNINGS belong to family findings, not to the router.
ROUTER_STATUSES: frozenset[Status] = frozenset({Status.PASS, Status.BLOCKED})


# --- validation helpers (mirrored from scan-gate/contracts.py) --------------


def _require(data: dict[str, Any], keys: list[str], ctx: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ContractError(f"{ctx}: missing required field(s): {', '.join(missing)}")


def _check_version(data: dict[str, Any], expected: str, ctx: str) -> str:
    version = data["schema_version"]
    if version != expected:
        raise ContractError(f"{ctx}: unsupported schema_version {version!r}; expected {expected!r}")
    return str(version)


def _coerce_enum(enum_cls: type[Enum], value: Any, ctx: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError:
        allowed = ", ".join(str(e.value) for e in enum_cls)
        raise ContractError(
            f"{ctx}: invalid {enum_cls.__name__} {value!r}; allowed: {allowed}"
        ) from None


def _coerce_enum_list(enum_cls: type[Enum], values: Any, ctx: str) -> list[Any]:
    return [_coerce_enum(enum_cls, v, ctx) for v in (values or [])]


def _require_mapping(value: Any, ctx: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{ctx}: expected an object, got {type(value).__name__}")
    return value


def _require_mapping_or_none(value: Any, ctx: str) -> dict[str, Any] | None:
    if value is not None and not isinstance(value, dict):
        raise ContractError(f"{ctx}: expected an object or null, got {type(value).__name__}")
    return value


def _require_list(value: Any, ctx: str) -> list[Any]:
    # Guard against silent corruption: `list("abc")` succeeds as ['a','b','c'],
    # so a string where a list is expected must be rejected, not iterated.
    if not isinstance(value, list):
        raise ContractError(f"{ctx}: expected an array, got {type(value).__name__}")
    return value


def _require_str(value: Any, ctx: str) -> str:
    # Identity/text fields must be strings so downstream string ops (e.g. the
    # index's claim-quality checks) fail closed here rather than crash later.
    if not isinstance(value, str):
        raise ContractError(f"{ctx}: expected a string, got {type(value).__name__}")
    return value


# --- contracts --------------------------------------------------------------


@dataclass
class ArtifactRef:
    """A reference to one typed evidence artifact.

    Either `path` (resolved by the index) or inline `content` (preferred in
    fixtures) carries the typed payload families probe. `authority` records who
    owns the artifact; families never let a non-product authority satisfy a
    claim that requires product authority.
    """

    id: str
    kind: ArtifactKind
    authority: Authority
    path: str | None = None
    content: dict[str, Any] | None = None
    produced_by: str | None = None
    claim_ids: list[str] = field(default_factory=list)
    stale: bool = False
    notes: str | None = None

    _REQUIRED = ("id", "kind", "authority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "authority": self.authority.value,
            "path": self.path,
            "content": self.content,
            "produced_by": self.produced_by,
            "claim_ids": list(self.claim_ids),
            "stale": self.stale,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactRef:
        _require(data, list(cls._REQUIRED), "ArtifactRef")
        return cls(
            id=_require_str(data["id"], "ArtifactRef.id"),
            kind=_coerce_enum(ArtifactKind, data["kind"], "ArtifactRef.kind"),
            authority=_coerce_enum(Authority, data["authority"], "ArtifactRef.authority"),
            path=data.get("path"),
            content=data.get("content"),
            produced_by=data.get("produced_by"),
            claim_ids=list(data.get("claim_ids", [])),
            stale=bool(data.get("stale", False)),
            notes=data.get("notes"),
        )


@dataclass
class Claim:
    """One claim selected by the Execution Loop for validation."""

    id: str
    text: str
    risk_surfaces: list[str] = field(default_factory=list)
    expected_families: list[FamilyId] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)

    _REQUIRED = ("id", "text")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "risk_surfaces": list(self.risk_surfaces),
            "expected_families": [f.value for f in self.expected_families],
            "required_artifacts": list(self.required_artifacts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        _require(data, list(cls._REQUIRED), "Claim")
        return cls(
            id=_require_str(data["id"], "Claim.id"),
            text=_require_str(data["text"], "Claim.text"),
            risk_surfaces=list(data.get("risk_surfaces", [])),
            expected_families=_coerce_enum_list(
                FamilyId, data.get("expected_families"), "Claim.expected_families"
            ),
            required_artifacts=list(data.get("required_artifacts", [])),
        )


@dataclass
class FamilyFinding:
    """One finding from one semantic family for one claim."""

    family_id: FamilyId
    claim_id: str
    status: Status
    evidence_refs: list[str] = field(default_factory=list)
    reason: str = ""
    remediation: str = ""
    risk_ref: str | None = None

    _REQUIRED = ("family_id", "claim_id", "status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id.value,
            "claim_id": self.claim_id,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
            "remediation": self.remediation,
            "risk_ref": self.risk_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FamilyFinding:
        _require(data, list(cls._REQUIRED), "FamilyFinding")
        return cls(
            family_id=_coerce_enum(FamilyId, data["family_id"], "FamilyFinding.family_id"),
            claim_id=data["claim_id"],
            status=_coerce_enum(Status, data["status"], "FamilyFinding.status"),
            evidence_refs=list(data.get("evidence_refs", [])),
            reason=data.get("reason", ""),
            remediation=data.get("remediation", ""),
            risk_ref=data.get("risk_ref"),
        )


@dataclass
class RouterFamily:
    """One routed family with the claims and evidence it should validate."""

    family_id: FamilyId
    claim_ids: list[str] = field(default_factory=list)
    reason: str = ""
    required_evidence: list[str] = field(default_factory=list)
    risk_references: list[str] = field(default_factory=list)

    _REQUIRED = ("family_id",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id.value,
            "claim_ids": list(self.claim_ids),
            "reason": self.reason,
            "required_evidence": list(self.required_evidence),
            "risk_references": list(self.risk_references),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouterFamily:
        _require(data, list(cls._REQUIRED), "RouterFamily")
        return cls(
            family_id=_coerce_enum(FamilyId, data["family_id"], "RouterFamily.family_id"),
            claim_ids=list(data.get("claim_ids", [])),
            reason=data.get("reason", ""),
            required_evidence=list(data.get("required_evidence", [])),
            risk_references=list(data.get("risk_references", [])),
        )


@dataclass
class RouterResult:
    """Router output: the smallest family set, or BLOCKED when routing cannot be trusted."""

    status: Status
    families: list[RouterFamily] = field(default_factory=list)
    blocked_on: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    _REQUIRED = ("status",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "families": [f.to_dict() for f in self.families],
            "blocked_on": list(self.blocked_on),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouterResult:
        _require(data, list(cls._REQUIRED), "RouterResult")
        status = _coerce_enum(Status, data["status"], "RouterResult.status")
        # Routing can only succeed or block; semantic FAIL/PASS_WITH_WARNINGS
        # come from family findings, never from routing itself. Fail closed on
        # an impossible router status rather than serialize it as valid.
        if status not in ROUTER_STATUSES:
            allowed = ", ".join(s.value for s in (Status.PASS, Status.BLOCKED))
            raise ContractError(
                f"RouterResult.status: must be one of {allowed}; got {status.value!r}"
            )
        return cls(
            status=status,
            families=[RouterFamily.from_dict(f) for f in data.get("families", [])],
            blocked_on=list(data.get("blocked_on", [])),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class EvidencePack:
    """The source of truth for one Validator run (`validator.evidence.v1`).

    Execution Loop builds it; Validator reads it. `source_boundary` partitions
    artifact ids/paths by authority so the reader can refuse to let a
    non-product artifact satisfy a product claim.
    """

    checkpoint: str
    source_boundary: dict[str, list[str]] = field(default_factory=dict)
    gate_plan: dict[str, Any] = field(default_factory=dict)
    step_complete: dict[str, Any] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    scan_gate_result: dict[str, Any] | None = None
    code_review_result: dict[str, Any] | None = None
    known_gaps: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION_EVIDENCE

    @staticmethod
    def required_fields() -> tuple[str, ...]:
        return ("schema_version", "checkpoint")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "checkpoint": self.checkpoint,
            "source_boundary": {k: list(v) for k, v in self.source_boundary.items()},
            "gate_plan": dict(self.gate_plan),
            "step_complete": dict(self.step_complete),
            "claims": [c.to_dict() for c in self.claims],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "scan_gate_result": self.scan_gate_result,
            "code_review_result": self.code_review_result,
            "known_gaps": list(self.known_gaps),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidencePack:
        _require(data, list(cls.required_fields()), "EvidencePack")
        _check_version(data, SCHEMA_VERSION_EVIDENCE, "EvidencePack")
        # Type-guard collection fields: wrong types (e.g. source_boundary: null,
        # or a bucket whose value is a string) must fail closed as ContractError,
        # never raise AttributeError or get silently shredded by list("abc").
        sb_raw = _require_mapping(data.get("source_boundary", {}), "EvidencePack.source_boundary")
        source_boundary: dict[str, list[str]] = {}
        for bucket, entries in sb_raw.items():
            _require_list(entries, f"EvidencePack.source_boundary[{bucket!r}]")
            source_boundary[bucket] = [str(e) for e in entries]
        return cls(
            checkpoint=data["checkpoint"],
            source_boundary=source_boundary,
            gate_plan=_require_mapping(data.get("gate_plan", {}), "EvidencePack.gate_plan"),
            step_complete=_require_mapping(
                data.get("step_complete", {}), "EvidencePack.step_complete"
            ),
            claims=[
                Claim.from_dict(c)
                for c in _require_list(data.get("claims", []), "EvidencePack.claims")
            ],
            artifacts=[
                ArtifactRef.from_dict(a)
                for a in _require_list(data.get("artifacts", []), "EvidencePack.artifacts")
            ],
            scan_gate_result=_require_mapping_or_none(
                data.get("scan_gate_result"), "EvidencePack.scan_gate_result"
            ),
            code_review_result=_require_mapping_or_none(
                data.get("code_review_result"), "EvidencePack.code_review_result"
            ),
            known_gaps=list(_require_list(data.get("known_gaps", []), "EvidencePack.known_gaps")),
            schema_version=data.get("schema_version", SCHEMA_VERSION_EVIDENCE),
        )


@dataclass
class ValidatorResult:
    """The authoritative output of one Validator run (`validator.result.v1`)."""

    status: Status
    checkpoint: str
    families_run: list[str] = field(default_factory=list)
    claims_validated: list[str] = field(default_factory=list)
    findings: list[FamilyFinding] = field(default_factory=list)
    evidence_used: list[str] = field(default_factory=list)
    blocked_on: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk_references_used: list[str] = field(default_factory=list)
    gate: str = GATE_NAME
    schema_version: str = SCHEMA_VERSION_RESULT

    @staticmethod
    def required_fields() -> tuple[str, ...]:
        return ("gate", "schema_version", "status", "checkpoint")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "checkpoint": self.checkpoint,
            "families_run": list(self.families_run),
            "claims_validated": list(self.claims_validated),
            "findings": [f.to_dict() for f in self.findings],
            "evidence_used": list(self.evidence_used),
            "blocked_on": list(self.blocked_on),
            "warnings": list(self.warnings),
            "risk_references_used": list(self.risk_references_used),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidatorResult:
        _require(data, list(cls.required_fields()), "ValidatorResult")
        _check_version(data, SCHEMA_VERSION_RESULT, "ValidatorResult")
        # `gate` is a const discriminator in the schema: a stale or foreign
        # result file must fail closed, not be re-emitted as authoritative.
        gate = data.get("gate", GATE_NAME)
        if gate != GATE_NAME:
            raise ContractError(f"ValidatorResult.gate: must be {GATE_NAME!r}; got {gate!r}")
        # families_run audits which semantic families ran; it is a closed set,
        # so typoed or risk-catalog labels must not validate as family ids.
        families_run = [
            _coerce_enum(FamilyId, fr, "ValidatorResult.families_run").value
            for fr in data.get("families_run", [])
        ]
        return cls(
            status=_coerce_enum(Status, data["status"], "ValidatorResult.status"),
            checkpoint=data["checkpoint"],
            families_run=families_run,
            claims_validated=list(data.get("claims_validated", [])),
            findings=[FamilyFinding.from_dict(f) for f in data.get("findings", [])],
            evidence_used=list(data.get("evidence_used", [])),
            blocked_on=list(data.get("blocked_on", [])),
            warnings=list(data.get("warnings", [])),
            risk_references_used=list(data.get("risk_references_used", [])),
            gate=gate,
            schema_version=data.get("schema_version", SCHEMA_VERSION_RESULT),
        )
