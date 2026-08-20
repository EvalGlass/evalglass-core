"""Tests for the digest-bound AuthorityGrant and its authority integration (M7 T3, G3/N2).

A grant approves specific digests; change any bound artifact and it stops matching,
so the gate falls back to informational (or blocked when expired) — never a pass.

See src/evalglass/core/grant.py, src/evalglass/core/authority.py, docs/TETA_REDESIGN.md §4.6.
"""

from __future__ import annotations

import hashlib

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.authority import (
    AuthorityInputs,
    AuthorityLevel,
    DatasetStatus,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.core.grant import (
    AuthorityGrant,
    GrantBinding,
    GrantStatus,
    GrantVerification,
    verify_grant,
)


def _d(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _grant(**overrides: object) -> AuthorityGrant:
    base: dict[str, object] = {
        "metric": "quality",
        "approver": "reviewer@example.com",
        "approved_at": "2026-07-18T00:00:00Z",
        "rationale": "validated over 200 items; LCB clears 0.8",
        "decision_policy_sha256": _d("policy"),
    }
    base.update(overrides)
    return AuthorityGrant(**base)  # type: ignore[arg-type]


# --- verify_grant ----------------------------------------------------------


def test_matched_when_all_declared_digests_agree() -> None:
    grant = _grant(dataset_validation_sha256=_d("data"))
    binding = GrantBinding(
        decision_policy_sha256=_d("policy"), dataset_validation_sha256=_d("data")
    )
    assert verify_grant(grant, binding).status is GrantStatus.MATCHED


def test_mismatch_when_policy_changes() -> None:
    grant = _grant()
    binding = GrantBinding(decision_policy_sha256=_d("policy-v2"))
    v = verify_grant(grant, binding)
    assert v.status is GrantStatus.MISMATCHED
    assert v.mismatched_fields == ("decision_policy_sha256",)


def test_mismatch_when_declared_dataset_absent_in_binding() -> None:
    grant = _grant(dataset_validation_sha256=_d("data"))
    binding = GrantBinding(decision_policy_sha256=_d("policy"))  # no dataset digest
    v = verify_grant(grant, binding)
    assert v.status is GrantStatus.MISMATCHED
    assert "dataset_validation_sha256" in v.mismatched_fields


def test_undeclared_slot_does_not_constrain() -> None:
    # Grant binds only the policy; a differing dataset digest it never approved is ignored.
    grant = _grant()
    binding = GrantBinding(decision_policy_sha256=_d("policy"), dataset_validation_sha256=_d("x"))
    assert verify_grant(grant, binding).status is GrantStatus.MATCHED


def test_expiry_only_when_now_supplied() -> None:
    grant = _grant(expires_at="2026-01-01T00:00:00Z")
    binding = GrantBinding(decision_policy_sha256=_d("policy"))
    assert verify_grant(grant, binding).status is GrantStatus.MATCHED  # no `now` -> not checked
    assert verify_grant(grant, binding, now="2026-07-18T00:00:00Z").status is GrantStatus.EXPIRED
    assert verify_grant(grant, binding, now="2025-06-01T00:00:00Z").status is GrantStatus.MATCHED


def test_round_trip() -> None:
    grant = _grant(
        dataset_validation_sha256=_d("data"),
        evaluator_capability_sha256=_d("eval"),
        study_evidence_sha256=_d("study"),
        expires_at="2027-01-01T00:00:00Z",
    )
    assert AuthorityGrant.from_dict(grant.to_dict()) == grant


@pytest.mark.parametrize(
    "kwargs",
    [
        {"approver": "  "},
        {"rationale": ""},
        {"decision_policy_sha256": "not-hex"},
        {"decision_policy_sha256": "abc"},
        {"dataset_validation_sha256": "ZZZ"},
    ],
)
def test_invalid_grants_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        _grant(**kwargs)


# --- authority integration -------------------------------------------------


def _gating_inputs(**overrides: object) -> AuthorityInputs:
    base: dict[str, object] = {
        "metric_status": MetricStatus.GATING,
        "dataset_status": DatasetStatus.VALIDATED,
        "threshold_approval": ThresholdApproval.APPROVED,
        "data_policy": DataPolicy.PERMITTED,
    }
    base.update(overrides)
    return AuthorityInputs(**base)  # type: ignore[arg-type]


def test_matched_grant_allows_gating() -> None:
    v = GrantVerification(GrantStatus.MATCHED)
    resolved = resolve_authority(_gating_inputs(grant_verification=v))
    assert resolved.can_gate is True


def test_mismatched_grant_forces_informational() -> None:
    v = GrantVerification(GrantStatus.MISMATCHED, ("decision_policy_sha256",))
    resolved = resolve_authority(_gating_inputs(grant_verification=v))
    assert resolved.level is AuthorityLevel.INFORMATIONAL
    assert resolved.can_gate is False
    assert "grant_mismatched" in resolved.reasons


def test_missing_grant_forces_informational() -> None:
    resolved = resolve_authority(
        _gating_inputs(grant_verification=GrantVerification(GrantStatus.MISSING))
    )
    assert resolved.can_gate is False
    assert "grant_missing" in resolved.reasons


def test_expired_grant_blocks() -> None:
    resolved = resolve_authority(
        _gating_inputs(grant_verification=GrantVerification(GrantStatus.EXPIRED))
    )
    assert resolved.blocked is True
    assert resolved.level is AuthorityLevel.GATING
    assert "grant_expired" in resolved.reasons


def test_no_grant_preserves_prior_behavior() -> None:
    assert resolve_authority(_gating_inputs()).can_gate is True
