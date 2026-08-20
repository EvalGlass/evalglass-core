"""FakeJudgeModel — deterministic, no-network judge adapter + call ledger (EG-M4-1b).

The required tier uses **fake** judge evidence only (CLAUDE.md §14): a judge call is
an *effect*, so it lives in an adapter, is deterministic, makes no network call and
imports no provider SDK, and records a call **ledger** so EGTS can prove which
examples were judged (and that forbidden ones were not). Every failure mode
(timeout / provider error / malformed / missing response) returns a typed
``Diagnostic`` and **no value** — a failed judge is not a low score (§9).
"""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.adapters.judge_fake import FakeJudgeModel
from evalglass.core import JudgeEvidenceStatus
from evalglass.harness.ports import JudgeModel, JudgeRequest


def _req(example_id: str = "e1", metric: str = "faithfulness", **ctx: Any) -> JudgeRequest:
    return JudgeRequest(
        example_id=example_id,
        metric=metric,
        input="q",
        output="a",
        reference=None,
        context=ctx,
    )


def test_is_a_judge_model() -> None:
    assert isinstance(FakeJudgeModel(), JudgeModel)


def test_ok_directive_returns_value_and_records_ledger() -> None:
    judge = FakeJudgeModel()
    result = judge.judge(_req(judge={"value": 0.8, "rationale": "grounded"}))
    assert result.status is JudgeEvidenceStatus.OK
    assert result.parsed_value == pytest.approx(0.8)
    assert result.raw_response is not None
    assert result.rationale == "grounded"
    assert judge.ledger == [("e1", "faithfulness")]


def test_default_value_used_without_directive() -> None:
    result = FakeJudgeModel(default_value=1.0).judge(_req())
    assert result.status is JudgeEvidenceStatus.OK
    assert result.parsed_value == pytest.approx(1.0)


def test_no_value_no_default_is_missing() -> None:
    result = FakeJudgeModel().judge(_req())
    assert result.status is JudgeEvidenceStatus.MISSING
    assert result.parsed_value is None


@pytest.mark.parametrize(
    ("mode", "status"),
    [
        ("timeout", JudgeEvidenceStatus.TIMEOUT),
        ("provider_error", JudgeEvidenceStatus.PROVIDER_ERROR),
        ("malformed", JudgeEvidenceStatus.MALFORMED),
        ("missing", JudgeEvidenceStatus.MISSING),
    ],
)
def test_failure_modes_carry_no_value_and_a_diagnostic(
    mode: str, status: JudgeEvidenceStatus
) -> None:
    result = FakeJudgeModel().judge(_req(judge={"mode": mode}))
    assert result.status is status
    assert result.parsed_value is None
    assert result.diagnostics  # a typed diagnostic explains the failure
    if mode == "malformed":
        # a response was received but could not be parsed — keep it for provenance
        assert result.raw_response is not None


def test_unknown_mode_fails_closed_as_provider_error() -> None:
    result = FakeJudgeModel().judge(_req(judge={"mode": "explode"}))
    assert result.status is JudgeEvidenceStatus.PROVIDER_ERROR
    assert result.parsed_value is None
    assert result.diagnostics


@pytest.mark.parametrize("bad", [True, "high", float("nan"), float("inf")])
def test_ok_directive_with_bad_value_fails_closed(bad: object) -> None:
    # a fixture-supplied non-numeric/non-finite value fails closed, never coerced or thrown
    result = FakeJudgeModel().judge(_req(judge={"value": bad}))
    assert result.status is JudgeEvidenceStatus.MALFORMED
    assert result.parsed_value is None
    assert result.diagnostics


def test_deterministic_same_request_same_result() -> None:
    r1 = FakeJudgeModel(default_value=0.5).judge(_req())
    r2 = FakeJudgeModel(default_value=0.5).judge(_req())
    assert (r1.status, r1.parsed_value, r1.raw_response) == (
        r2.status,
        r2.parsed_value,
        r2.raw_response,
    )


def test_ledger_records_every_call_in_order() -> None:
    judge = FakeJudgeModel(default_value=0.5)
    judge.judge(_req(example_id="e1"))
    judge.judge(_req(example_id="e2", metric="relevance"))
    assert judge.ledger == [("e1", "faithfulness"), ("e2", "relevance")]
