"""Public skill contracts (EG-M3-1).

JSON-primary typed artifacts the integration-time skill emits and consumes:
:class:`HostDiscoveryReport` (what a read-only inspection found),
:class:`InstallPlan` (what the skill proposes — never authoritative), and
:class:`DataPolicyPrompt` (an unanswered data-boundary question the host must
resolve). Every contract round-trips through ``to_dict``/``from_dict`` and parses
fail-closed (`CLAUDE.md §1`; mirrors the core contract discipline). Stdlib-only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.installer._validation import (
    InstallerError,
    _as_mapping,
    _mapping_list,
    _require_bool,
    _require_str,
    _str_list,
)

__all__ = [
    "AuthorityRecord",
    "DataPolicyPrompt",
    "EvalglassLock",
    "HostDiscoveryReport",
    "InstallPlan",
    "InstallerError",
    "ManagedFileRecord",
    "VendorManifest",
]


@dataclass(frozen=True)
class DataPolicyPrompt:
    """An unanswered data-boundary question. The skill never auto-answers it.

    Its presence in a report/plan means the host must decide a source's data policy
    before that source can egress (e.g. to a replay subprocess). ``choices`` always
    offers the conservative options; the skill picks none of them.
    """

    subject: str
    question: str
    choices: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "question": self.question, "choices": list(self.choices)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "DataPolicyPrompt")
        choices = _str_list(m, "choices", "DataPolicyPrompt", required=True)
        if not choices:
            raise InstallerError("DataPolicyPrompt: 'choices' must be a non-empty list")
        return cls(
            subject=_require_str(m, "subject", "DataPolicyPrompt"),
            question=_require_str(m, "question", "DataPolicyPrompt"),
            choices=choices,
        )


@dataclass(frozen=True)
class HostDiscoveryReport:
    """The result of a conservative, read-only host inspection (EG-M3-1)."""

    root: str
    language: str
    has_evals_dir: bool = False
    llm_call_sites: list[dict[str, Any]] = field(default_factory=list)
    trace_candidates: list[str] = field(default_factory=list)
    eval_assets: list[str] = field(default_factory=list)
    ci_configs: list[str] = field(default_factory=list)
    ignore_files: list[str] = field(default_factory=list)
    data_policy_prompts: list[DataPolicyPrompt] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "language": self.language,
            "has_evals_dir": self.has_evals_dir,
            "llm_call_sites": [dict(c) for c in self.llm_call_sites],
            "trace_candidates": list(self.trace_candidates),
            "eval_assets": list(self.eval_assets),
            "ci_configs": list(self.ci_configs),
            "ignore_files": list(self.ignore_files),
            "data_policy_prompts": [p.to_dict() for p in self.data_policy_prompts],
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "HostDiscoveryReport")
        return cls(
            root=_require_str(m, "root", "HostDiscoveryReport"),
            language=_require_str(m, "language", "HostDiscoveryReport"),
            has_evals_dir=(
                _require_bool(m, "has_evals_dir", "HostDiscoveryReport")
                if "has_evals_dir" in m
                else False
            ),
            llm_call_sites=[
                dict(c) for c in _mapping_list(m, "llm_call_sites", "HostDiscoveryReport")
            ],
            trace_candidates=_str_list(m, "trace_candidates", "HostDiscoveryReport"),
            eval_assets=_str_list(m, "eval_assets", "HostDiscoveryReport"),
            ci_configs=_str_list(m, "ci_configs", "HostDiscoveryReport"),
            ignore_files=_str_list(m, "ignore_files", "HostDiscoveryReport"),
            data_policy_prompts=[
                DataPolicyPrompt.from_dict(p)
                for p in _mapping_list(m, "data_policy_prompts", "HostDiscoveryReport")
            ],
            open_questions=_str_list(m, "open_questions", "HostDiscoveryReport"),
        )


@dataclass(frozen=True)
class InstallPlan:
    """A reviewable, proposed install plan. It can propose, never authorize.

    ``proposed_host_assets`` are host-owned scaffolds (provisional, non-authoritative);
    ``preserved_paths`` are existing host-owned truth left untouched. ``grants_authority``
    is structurally pinned to ``False`` — a plan that tried to grant gating authority is a
    contract violation and fails closed.
    """

    root: str
    managed_root: str
    proposed_host_assets: list[str] = field(default_factory=list)
    preserved_paths: list[str] = field(default_factory=list)
    questions: list[DataPolicyPrompt] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    grants_authority: bool = False

    def __post_init__(self) -> None:
        if self.grants_authority:
            raise InstallerError(
                "InstallPlan: grants_authority must be False — a plan cannot authorize"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "managed_root": self.managed_root,
            "proposed_host_assets": list(self.proposed_host_assets),
            "preserved_paths": list(self.preserved_paths),
            "questions": [q.to_dict() for q in self.questions],
            "blockers": list(self.blockers),
            "grants_authority": self.grants_authority,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "InstallPlan")
        grants = (
            _require_bool(m, "grants_authority", "InstallPlan")
            if "grants_authority" in m
            else False
        )
        return cls(
            root=_require_str(m, "root", "InstallPlan"),
            managed_root=_require_str(m, "managed_root", "InstallPlan"),
            proposed_host_assets=_str_list(m, "proposed_host_assets", "InstallPlan"),
            preserved_paths=_str_list(m, "preserved_paths", "InstallPlan"),
            questions=[
                DataPolicyPrompt.from_dict(q) for q in _mapping_list(m, "questions", "InstallPlan")
            ],
            blockers=_str_list(m, "blockers", "InstallPlan"),
            grants_authority=grants,
        )


@dataclass(frozen=True)
class ManagedFileRecord:
    """One vendored managed file: its host-relative path, content sha256, and purpose.

    ``host_patched`` is set on re-vendor when the on-disk checksum diverges from the
    recorded one — a host edit to a managed file that must be surfaced, never hidden.
    """

    path: str
    sha256: str
    purpose: str
    host_patched: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "purpose": self.purpose,
            "host_patched": self.host_patched,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "ManagedFileRecord")
        return cls(
            path=_require_str(m, "path", "ManagedFileRecord"),
            sha256=_require_str(m, "sha256", "ManagedFileRecord"),
            purpose=_require_str(m, "purpose", "ManagedFileRecord"),
            host_patched=(
                _require_bool(m, "host_patched", "ManagedFileRecord")
                if "host_patched" in m
                else False
            ),
        )


@dataclass(frozen=True)
class VendorManifest:
    """The managed-file boundary: every framework file vendored under ``managed_root``.

    Records a sha256 per managed file so a re-vendor (or audit) can detect host patches
    exactly. It describes only the managed runtime — never host-owned truth.
    """

    schema_version: str
    source_version: str
    managed_root: str
    files: list[ManagedFileRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_version": self.source_version,
            "managed_root": self.managed_root,
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "VendorManifest")
        return cls(
            schema_version=_require_str(m, "schema_version", "VendorManifest"),
            source_version=_require_str(m, "source_version", "VendorManifest"),
            managed_root=_require_str(m, "managed_root", "VendorManifest"),
            files=[
                ManagedFileRecord.from_dict(f) for f in _mapping_list(m, "files", "VendorManifest")
            ],
        )


@dataclass(frozen=True)
class EvalglassLock:
    """The installed runtime identity: framework version, source ref, features, extras."""

    schema_version: str
    framework_version: str
    source_ref: str
    installed_features: list[str] = field(default_factory=list)
    optional_extras: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "framework_version": self.framework_version,
            "source_ref": self.source_ref,
            "installed_features": list(self.installed_features),
            "optional_extras": list(self.optional_extras),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "EvalglassLock")
        return cls(
            schema_version=_require_str(m, "schema_version", "EvalglassLock"),
            framework_version=_require_str(m, "framework_version", "EvalglassLock"),
            source_ref=_require_str(m, "source_ref", "EvalglassLock"),
            installed_features=_str_list(m, "installed_features", "EvalglassLock"),
            optional_extras=_str_list(m, "optional_extras", "EvalglassLock"),
        )


@dataclass(frozen=True)
class AuthorityRecord:
    """Host-owned approval ledger — the explicit record of what a human has validated.

    **Empty by default**, so a freshly scaffolded repo grants no metric gating authority:
    no approved thresholds, no validated datasets, no calibrated judges. A host fills this
    in only after validating gold, approving thresholds, and calibrating judges (P15). The
    skill never populates it (no silent authority).
    """

    approved_thresholds: list[str] = field(default_factory=list)
    validated_datasets: list[str] = field(default_factory=list)
    calibrated_judges: list[str] = field(default_factory=list)

    def grants_any_authority(self) -> bool:
        return bool(self.approved_thresholds or self.validated_datasets or self.calibrated_judges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_thresholds": list(self.approved_thresholds),
            "validated_datasets": list(self.validated_datasets),
            "calibrated_judges": list(self.calibrated_judges),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "AuthorityRecord")
        return cls(
            approved_thresholds=_str_list(m, "approved_thresholds", "AuthorityRecord"),
            validated_datasets=_str_list(m, "validated_datasets", "AuthorityRecord"),
            calibrated_judges=_str_list(m, "calibrated_judges", "AuthorityRecord"),
        )
