"""Optional live judge lane — port conformance, missing-prereq skip, response mapping (EG-M4-5).

Hermetic: the network call is monkeypatched, so this runs in the required suite without any
real egress. The lane's real proof is deletion safety (the import-boundary guard); these tests
pin its contract: it implements the ``JudgeModel`` port, skips when prerequisites are absent,
and maps a provider response (or failure) into a ``JudgeResult`` like the fake adapter.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from evalglass.core import JudgeEvidenceStatus
from evalglass.harness.ports import JudgeModel, JudgeRequest

# The lane is optional/deletable: skip (don't error) if it has been removed (EG-M4-5).
judge_live = pytest.importorskip("evalglass.adapters.judge_live")
LiveJudgeModel = judge_live.LiveJudgeModel
MissingPrerequisite = judge_live.MissingPrerequisite

_ENDPOINT = "https://judge.example/score"


def _req() -> JudgeRequest:
    return JudgeRequest(example_id="e1", metric="faithfulness", input="q", output="a")


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch, *, body: bytes | None = None, exc: Exception | None = None
) -> None:
    def fake_urlopen(request: object, timeout: float | None = None) -> io.BytesIO:
        if exc is not None:
            raise exc
        assert body is not None
        return io.BytesIO(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def test_implements_the_judge_model_port() -> None:
    assert isinstance(LiveJudgeModel(endpoint=_ENDPOINT), JudgeModel)


def test_missing_endpoint_skips() -> None:
    with pytest.raises(MissingPrerequisite):
        LiveJudgeModel(endpoint=None)


def test_non_https_endpoint_skips() -> None:
    with pytest.raises(MissingPrerequisite):
        LiveJudgeModel(endpoint="http://insecure/score")


def test_ok_response_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, body=json.dumps({"score": 0.8, "rationale": "grounded"}).encode())
    result = LiveJudgeModel(endpoint=_ENDPOINT, api_key="k").judge(_req())
    assert result.status is JudgeEvidenceStatus.OK
    assert result.parsed_value == pytest.approx(0.8)
    assert result.rationale == "grounded"


def test_non_json_response_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, body=b"not json")
    result = LiveJudgeModel(endpoint=_ENDPOINT).judge(_req())
    assert result.status is JudgeEvidenceStatus.MALFORMED
    assert result.parsed_value is None


def test_no_score_field_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, body=json.dumps({"reason": "x"}).encode())
    result = LiveJudgeModel(endpoint=_ENDPOINT).judge(_req())
    assert result.status is JudgeEvidenceStatus.MALFORMED


def test_infinite_score_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, body=b'{"score": 1e10000}')  # JSON parses this to inf
    result = LiveJudgeModel(endpoint=_ENDPOINT).judge(_req())
    assert result.status is JudgeEvidenceStatus.MALFORMED


def test_nan_token_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, body=b'{"score": NaN}')  # non-standard JSON token, rejected
    result = LiveJudgeModel(endpoint=_ENDPOINT).judge(_req())
    assert result.status is JudgeEvidenceStatus.MALFORMED


def test_network_error_is_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("boom"))
    result = LiveJudgeModel(endpoint=_ENDPOINT).judge(_req())
    assert result.status is JudgeEvidenceStatus.PROVIDER_ERROR
    assert result.diagnostics
