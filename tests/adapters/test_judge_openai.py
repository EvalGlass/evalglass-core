"""OpenAI-compatible judge lane (ADR 0040) — behavior + fail-closed contract.

The adapter is generic *transport only*: it scores a host-injected rubric with any
OpenAI-compatible ``/chat/completions`` endpoint. The per-metric rubric is domain content
the host supplies at construction — proven here to travel from the host into the request,
never from the framework. All failure edges (absent config, plaintext egress, provider
error, malformed content, no finite score) fail closed to a skip or non-``OK`` evidence,
never a fabricated low score. Hermetic: ``urlopen`` is faked; no network.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from evalglass.adapters.judge_openai import OpenAICompatibleJudgeModel
from evalglass.core import JudgeEvidenceStatus
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import JudgeRequest

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_RUBRICS = {"wf.faithfulness": "Is every claim grounded in the input? Score the grounded fraction."}


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, n: int = -1) -> bytes:
        return self._payload[:n] if n and n > 0 else self._payload


def _envelope(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, payload: bytes, sink: list[Any]) -> None:
    def fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResp:
        sink.append(req)
        return _FakeResp(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def _request(metric: str = "wf.faithfulness", output: Any = None) -> JudgeRequest:
    return JudgeRequest(
        example_id="ex1",
        metric=metric,
        input="sensor evidence EVID_1",
        output=output if output is not None else {"claim": "x"},
        rubric_ref="wf.faithfulness",
    )


# --------------------------- fail-closed prerequisites ---------------------------


def test_absent_endpoint_skips() -> None:
    with pytest.raises(MissingPrerequisite):
        OpenAICompatibleJudgeModel(endpoint=None, model="m", rubrics=_RUBRICS)


def test_plaintext_endpoint_refused() -> None:
    with pytest.raises(MissingPrerequisite):
        OpenAICompatibleJudgeModel(
            endpoint="http://insecure/v1/chat/completions", model="m", rubrics=_RUBRICS
        )


def test_absent_model_skips() -> None:
    with pytest.raises(MissingPrerequisite):
        OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="", rubrics=_RUBRICS)


# --------------------------- happy path + host rubric injection ---------------------------


def test_scores_openai_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope('{"score": 0.8, "rationale": "mostly grounded"}'), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    result = judge.judge(_request())
    assert result.status is JudgeEvidenceStatus.OK
    assert result.parsed_value == 0.8
    assert result.rationale == "mostly grounded"


def test_host_rubric_travels_into_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('{"score": 1.0}'), sink)
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    judge.judge(_request())
    body = json.loads(sink[0].data.decode("utf-8"))
    # The domain rubric is host-supplied — it must appear in the outgoing prompt, not be
    # baked into the framework adapter.
    prompt = json.dumps(body["messages"])
    assert "grounded fraction" in prompt
    assert body["model"] == "m"
    assert sink[0].headers.get("Authorization") == "Bearer k"


def test_unknown_metric_falls_back_to_generic_rubric(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('{"score": 0.5}'), sink)
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics={}, api_key="k")
    result = judge.judge(_request(metric="unmapped"))
    assert result.status is JudgeEvidenceStatus.OK  # a missing rubric is not an error


@pytest.mark.parametrize(("raw", "expected"), [(1.5, 1.0), (-0.2, 0.0), (0.3, 0.3)])
def test_score_is_clamped_to_unit_range(
    monkeypatch: pytest.MonkeyPatch, raw: float, expected: float
) -> None:
    _patch_urlopen(monkeypatch, _envelope(json.dumps({"score": raw})), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    assert judge.judge(_request()).parsed_value == expected


def test_value_key_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope('{"value": 0.6}'), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    assert judge.judge(_request()).parsed_value == 0.6


def test_markdown_fenced_json_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope('```json\n{"score": 0.5}\n```'), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    assert judge.judge(_request()).parsed_value == 0.5


def test_untrusted_input_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('{"score": 1.0}'), sink)
    judge = OpenAICompatibleJudgeModel(
        endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k", max_chars=100
    )
    big = JudgeRequest(
        example_id="e", metric="wf.faithfulness", input="A" * 10_000, output="B" * 10_000
    )
    judge.judge(big)
    body = sink[0].data.decode("utf-8")
    # The 10k-char input/output were truncated to the cap: no long run survives in the prompt.
    assert "A" * 200 not in body
    assert "B" * 200 not in body


# --------------------------- non-OK evidence (never a low score) ---------------------------


def test_malformed_content_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope("not json at all"), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    result = judge.judge(_request())
    assert result.status is JudgeEvidenceStatus.MALFORMED
    assert result.parsed_value is None


def test_no_finite_score_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope('{"rationale": "no number here"}'), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    result = judge.judge(_request())
    assert result.status is JudgeEvidenceStatus.MALFORMED
    assert result.parsed_value is None


def test_nan_score_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope('{"score": NaN}'), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    assert judge.judge(_request()).status is JudgeEvidenceStatus.MALFORMED


def test_boolean_score_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, _envelope('{"score": true}'), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    assert judge.judge(_request()).status is JudgeEvidenceStatus.MALFORMED


def test_empty_envelope_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, json.dumps({"choices": []}).encode("utf-8"), [])
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    assert judge.judge(_request()).status is JudgeEvidenceStatus.MALFORMED


def test_provider_error_is_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(req: Any, timeout: float | None = None) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="k")
    result = judge.judge(_request())
    assert result.status is JudgeEvidenceStatus.PROVIDER_ERROR
    assert result.parsed_value is None


# --------------------------- C1 promotion: new adapter params ---------------------------


def test_json_object_response_format_is_sent_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('{"score": 0.5}'), sink)
    judge = OpenAICompatibleJudgeModel(endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS)
    judge.judge(_request())
    body = json.loads(sink[0].data)
    assert body["response_format"] == {"type": "json_object"}


def test_text_response_format_omits_the_field_and_still_parses_fenced_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An endpoint without json_object support: the field is omitted and a fenced reply still parses.
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('```json\n{"score": 0.4}\n```'), sink)
    judge = OpenAICompatibleJudgeModel(
        endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, response_format="text"
    )
    result = judge.judge(_request())
    assert "response_format" not in json.loads(sink[0].data)
    assert result.status is JudgeEvidenceStatus.OK
    assert result.parsed_value == pytest.approx(0.4)


def test_non_secret_headers_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('{"score": 1.0}'), sink)
    judge = OpenAICompatibleJudgeModel(
        endpoint=_ENDPOINT,
        model="m",
        rubrics=_RUBRICS,
        headers={"HTTP-Referer": "https://example.com", "X-Title": "evalglass"},
    )
    judge.judge(_request())
    assert sink[0].headers["Http-referer"] == "https://example.com"
    assert sink[0].headers["X-title"] == "evalglass"


def test_a_configured_header_cannot_override_the_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defense in depth: even if a header slips past the config allowlist, the real credential wins.
    sink: list[Any] = []
    _patch_urlopen(monkeypatch, _envelope('{"score": 1.0}'), sink)
    judge = OpenAICompatibleJudgeModel(
        endpoint=_ENDPOINT, model="m", rubrics=_RUBRICS, api_key="real", headers={"X-Other": "v"}
    )
    judge.judge(_request())
    assert sink[0].headers["Authorization"] == "Bearer real"


def test_loopback_http_allowed_only_under_explicit_policy() -> None:
    with pytest.raises(MissingPrerequisite):
        OpenAICompatibleJudgeModel(endpoint="http://127.0.0.1:8000/v1", model="m")
    judge = OpenAICompatibleJudgeModel(
        endpoint="http://127.0.0.1:8000/v1", model="m", allow_loopback=True
    )
    assert judge.capability.name == "MEASUREMENT"
