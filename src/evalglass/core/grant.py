"""Digest-bound AuthorityGrant: an approval tied to what it approved (M7 T3, G3).

Alpha's approval was an inline ``"approved"`` token: nothing bound it to the
threshold value, dataset, rubric, or policy it blessed, so a host could approve a
gate and then silently change the decision policy or dataset underneath it. The
redesign's rule (N2) is *no authority without a digest match*: a grant carries the
SHA-256 of every artifact it approved, and the core re-verifies each against the
current run. Edit the decision policy, the dataset validation, the evaluator
capability, or the study, and the grant stops matching — the gate falls back to
informational (never earned authority for *this* rig) rather than passing.

The core never reads the clock; expiry is checked only if the harness passes the
current timestamp (ISO-8601, string-comparable). The tool still never *writes* a
grant — a human authors and approves it. Effect-free, stdlib-only.
See ``docs/TETA_REDESIGN.md`` §4.6.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import ContractError, _as_mapping, _opt_str, _require_str

_HEX = frozenset("0123456789abcdef")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in _HEX for c in value)


def _require_digest(m: Mapping[str, Any], key: str, ctx: str) -> str:
    value = _require_str(m, key, ctx)
    if not _is_sha256(value):
        raise ContractError(f"{ctx}: '{key}' must be a 64-char lowercase hex sha256")
    return value


def _opt_digest(m: Mapping[str, Any], key: str, ctx: str) -> str | None:
    value = _opt_str(m, key, ctx)
    if value is not None and not _is_sha256(value):
        raise ContractError(f"{ctx}: '{key}' must be a 64-char lowercase hex sha256")
    return value


class GrantStatus(enum.StrEnum):
    MATCHED = "matched"  # every bound digest matches the current run
    MISMATCHED = "mismatched"  # a bound digest differs — the approval doesn't cover this rig
    EXPIRED = "expired"  # past the grant's expiry (checked only when the harness supplies `now`)
    MISSING = "missing"  # a grant was required for this gate but none was supplied


@dataclass(frozen=True)
class GrantBinding:
    """The current run's digests, to verify a grant against."""

    decision_policy_sha256: str
    dataset_validation_sha256: str | None = None
    evaluator_capability_sha256: str | None = None
    study_evidence_sha256: str | None = None


@dataclass(frozen=True)
class GrantVerification:
    """Outcome of verifying a grant against a run's bindings."""

    status: GrantStatus
    mismatched_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status.value}
        if self.mismatched_fields:
            out["mismatched_fields"] = list(self.mismatched_fields)
        return out


@dataclass(frozen=True)
class AuthorityGrant:
    """A human approval bound to the digests of exactly what it approved."""

    metric: str
    approver: str
    approved_at: str
    rationale: str
    decision_policy_sha256: str
    dataset_validation_sha256: str | None = None
    evaluator_capability_sha256: str | None = None
    study_evidence_sha256: str | None = None
    expires_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("metric", "approver", "approved_at", "rationale"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"AuthorityGrant.{name} must be a non-empty string")
        for name in (
            "decision_policy_sha256",
            "dataset_validation_sha256",
            "evaluator_capability_sha256",
            "study_evidence_sha256",
        ):
            value = getattr(self, name)
            if value is not None and not _is_sha256(value):
                raise ContractError(f"AuthorityGrant.{name} must be a 64-char lowercase hex sha256")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "approver": self.approver,
            "approved_at": self.approved_at,
            "rationale": self.rationale,
            "decision_policy_sha256": self.decision_policy_sha256,
        }
        for name in (
            "dataset_validation_sha256",
            "evaluator_capability_sha256",
            "study_evidence_sha256",
            "expires_at",
        ):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "AuthorityGrant")
        return cls(
            metric=_require_str(m, "metric", "AuthorityGrant"),
            approver=_require_str(m, "approver", "AuthorityGrant"),
            approved_at=_require_str(m, "approved_at", "AuthorityGrant"),
            rationale=_require_str(m, "rationale", "AuthorityGrant"),
            decision_policy_sha256=_require_digest(m, "decision_policy_sha256", "AuthorityGrant"),
            dataset_validation_sha256=_opt_digest(m, "dataset_validation_sha256", "AuthorityGrant"),
            evaluator_capability_sha256=_opt_digest(
                m, "evaluator_capability_sha256", "AuthorityGrant"
            ),
            study_evidence_sha256=_opt_digest(m, "study_evidence_sha256", "AuthorityGrant"),
            expires_at=_opt_str(m, "expires_at", "AuthorityGrant"),
        )


def verify_grant(
    grant: AuthorityGrant, binding: GrantBinding, *, now: str | None = None
) -> GrantVerification:
    """Verify a grant against a run's bindings. Pure; the core never reads the clock.

    Each digest the grant *declares* (non-None) must equal the run's binding for that
    slot; a declared digest whose binding is absent or different is a mismatch. Expiry
    is checked only when ``now`` is supplied (ISO-8601 strings compare chronologically).
    """
    if now is not None and grant.expires_at is not None and now > grant.expires_at:
        return GrantVerification(GrantStatus.EXPIRED)

    mismatched: list[str] = []
    checks = (
        ("decision_policy_sha256", grant.decision_policy_sha256, binding.decision_policy_sha256),
        (
            "dataset_validation_sha256",
            grant.dataset_validation_sha256,
            binding.dataset_validation_sha256,
        ),
        (
            "evaluator_capability_sha256",
            grant.evaluator_capability_sha256,
            binding.evaluator_capability_sha256,
        ),
        ("study_evidence_sha256", grant.study_evidence_sha256, binding.study_evidence_sha256),
    )
    for field_name, approved, current in checks:
        if approved is not None and approved != current:
            mismatched.append(field_name)
    if mismatched:
        return GrantVerification(GrantStatus.MISMATCHED, tuple(mismatched))
    return GrantVerification(GrantStatus.MATCHED)
