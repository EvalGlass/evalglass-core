"""Stable data contracts for the scan-gate skill.

Stdlib-only (dataclasses + enum + json), matching the EvalGlass "every dependency
is vendored cost" ethos. The JSON Schemas under ../schemas/ are the external
contract; these dataclasses are the runtime model + validation. `from_dict`
tolerates unknown keys so the schema can evolve additively.

Statuses mirror the Scan Gate architecture: PASS / WARN / BLOCKED / FAIL.
BLOCKED (missing proof) is never silently downgraded to PASS/WARN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION_REQUEST = "scan-gate.request.v1"
SCHEMA_VERSION_RESULT = "scan-gate.result.v1"


class ContractError(ValueError):
    """Raised when a payload violates a contract (bad enum, missing field)."""


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class Severity(str, Enum):
    FAIL = "fail"
    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


class Profile(str, Enum):
    FAST = "fast"
    MAIN = "main"
    REQUIRED = "required"


# Public enum value-sets for ToolLedgerEntry (mirror scan-result.schema.json).
NETWORK_MODES = frozenset({"disabled", "controlled", "enabled"})
ADAPTER_STATUSES = frozenset({"completed", "skipped", "error", "timeout"})


def _require(data: dict[str, Any], keys: list[str], ctx: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ContractError(f"{ctx}: missing required field(s): {', '.join(missing)}")


def _check_version(data: dict[str, Any], expected: str, ctx: str) -> str:
    version = data["schema_version"]
    if version != expected:
        raise ContractError(f"{ctx}: unsupported schema_version {version!r}; expected {expected!r}")
    return str(version)


def _one_of(value: Any, allowed: frozenset[str], ctx: str) -> str:
    if value not in allowed:
        raise ContractError(
            f"{ctx}: invalid value {value!r}; allowed: {', '.join(sorted(allowed))}"
        )
    return str(value)


def _coerce_enum(enum_cls: type[Enum], value: Any, ctx: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError:
        allowed = ", ".join(str(e.value) for e in enum_cls)
        raise ContractError(
            f"{ctx}: invalid {enum_cls.__name__} {value!r}; allowed: {allowed}"
        ) from None


@dataclass(frozen=True, slots=True)
class Finding:
    """One normalized policy finding."""

    id: str
    rule_id: str
    severity: Severity
    surface: str
    evidence: str
    tool: str
    tool_version: str
    policy_version: str
    recommendation: str
    file: str | None = None
    line: int | None = None

    _REQUIRED = (
        "id",
        "rule_id",
        "severity",
        "surface",
        "evidence",
        "tool",
        "tool_version",
        "policy_version",
        "recommendation",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "surface": self.surface,
            "file": self.file,
            "line": self.line,
            "evidence": self.evidence,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "policy_version": self.policy_version,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        _require(data, list(cls._REQUIRED), "Finding")
        return cls(
            id=data["id"],
            rule_id=data["rule_id"],
            severity=_coerce_enum(Severity, data["severity"], "Finding.severity"),
            surface=data["surface"],
            evidence=data["evidence"],
            tool=data["tool"],
            tool_version=data["tool_version"],
            policy_version=data["policy_version"],
            recommendation=data["recommendation"],
            file=data.get("file"),
            line=data.get("line"),
        )


@dataclass(frozen=True, slots=True)
class ToolLedgerEntry:
    """Audit record of one detector/adapter invocation."""

    tool: str
    version: str
    network: str  # "disabled" | "controlled" | "enabled"
    adapter_status: str  # "completed" | "skipped" | "error" | "timeout"
    exit_code: int | None = None
    raw_output_path: str | None = None
    skipped_reason: str | None = None
    findings_count: int = 0

    _REQUIRED = ("tool", "version", "network", "adapter_status")

    def __post_init__(self) -> None:
        _one_of(self.network, NETWORK_MODES, "ToolLedgerEntry.network")
        _one_of(self.adapter_status, ADAPTER_STATUSES, "ToolLedgerEntry.adapter_status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "version": self.version,
            "network": self.network,
            "adapter_status": self.adapter_status,
            "exit_code": self.exit_code,
            "raw_output_path": self.raw_output_path,
            "skipped_reason": self.skipped_reason,
            "findings_count": self.findings_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolLedgerEntry:
        _require(data, list(cls._REQUIRED), "ToolLedgerEntry")
        return cls(
            tool=data["tool"],
            version=data["version"],
            network=data["network"],
            adapter_status=data["adapter_status"],
            exit_code=data.get("exit_code"),
            raw_output_path=data.get("raw_output_path"),
            skipped_reason=data.get("skipped_reason"),
            findings_count=data.get("findings_count", 0),
        )


@dataclass
class ScanRequest:
    """Inputs to one scan run."""

    scan_id: str
    repo_root: str
    base_ref: str
    head_ref: str
    profile: Profile
    policy_ref: str
    include_untracked: bool = True
    schema_version: str = SCHEMA_VERSION_REQUEST

    @staticmethod
    def required_fields() -> tuple[str, ...]:
        return (
            "schema_version",
            "scan_id",
            "repo_root",
            "base_ref",
            "head_ref",
            "profile",
            "policy_ref",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scan_id": self.scan_id,
            "repo_root": self.repo_root,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "profile": self.profile.value,
            "policy_ref": self.policy_ref,
            "include_untracked": self.include_untracked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanRequest:
        _require(
            data,
            [
                "schema_version",
                "scan_id",
                "repo_root",
                "base_ref",
                "head_ref",
                "profile",
                "policy_ref",
            ],
            "ScanRequest",
        )
        _check_version(data, SCHEMA_VERSION_REQUEST, "ScanRequest")
        return cls(
            scan_id=data["scan_id"],
            repo_root=data["repo_root"],
            base_ref=data["base_ref"],
            head_ref=data["head_ref"],
            profile=_coerce_enum(Profile, data["profile"], "ScanRequest.profile"),
            policy_ref=data["policy_ref"],
            include_untracked=data.get("include_untracked", True),
            schema_version=data.get("schema_version", SCHEMA_VERSION_REQUEST),
        )


@dataclass
class ScanResult:
    """The authoritative output of a scan run."""

    scan_id: str
    status: Status
    policy_version: str
    profile_run: str
    findings: list[Finding] = field(default_factory=list)
    tool_ledger: list[ToolLedgerEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION_RESULT

    @staticmethod
    def required_fields() -> tuple[str, ...]:
        return ("schema_version", "scan_id", "status", "policy_version", "profile_run")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scan_id": self.scan_id,
            "status": self.status.value,
            "policy_version": self.policy_version,
            "profile_run": self.profile_run,
            "summary": dict(self.summary),
            "findings": [f.to_dict() for f in self.findings],
            "tool_ledger": [t.to_dict() for t in self.tool_ledger],
            "environment": dict(self.environment),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanResult:
        _require(
            data,
            ["schema_version", "scan_id", "status", "policy_version", "profile_run"],
            "ScanResult",
        )
        _check_version(data, SCHEMA_VERSION_RESULT, "ScanResult")
        return cls(
            scan_id=data["scan_id"],
            status=_coerce_enum(Status, data["status"], "ScanResult.status"),
            policy_version=data["policy_version"],
            profile_run=data["profile_run"],
            findings=[Finding.from_dict(f) for f in data.get("findings", [])],
            tool_ledger=[ToolLedgerEntry.from_dict(t) for t in data.get("tool_ledger", [])],
            summary=dict(data.get("summary", {})),
            environment=dict(data.get("environment", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION_RESULT),
        )
