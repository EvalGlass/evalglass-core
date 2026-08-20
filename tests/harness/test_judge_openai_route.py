"""OpenAI-compatible judge as a first-class measurement route (config -> run -> Score).

The lane is promoted into the config-driven path: ``judge.adapter: openai_compatible`` produces
ordinary ``JudgeEvidence`` consumed by the existing pure ``judge_score@1`` evaluator, over the same
egress-gated collector as fake/command. These tests are hermetic — ``urllib.request.urlopen`` is
faked, so no socket opens and no provider SDK is imported. They prove: the real capability is
``MEASUREMENT`` yet an uncalibrated judge still cannot gate; the credential is read from the
environment only at effect time and never persisted; a denied-egress subject makes no call; and a
provider/parse failure carries no numeric score.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import AuthorityLevel, ScoreStatus, Verdict
from evalglass.core.authority import JudgeCapability
from evalglass.harness.config import JudgeConfig, RuntimeConfig
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.runner import _build_judge_model, run_config

_ENDPOINT = "https://judge.test/v1/chat/completions"


# --------------------------------------------------------------------------- #
# Transport injection helpers (hermetic — no real socket)
# --------------------------------------------------------------------------- #


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, n: int = -1) -> bytes:
        return self._payload[:n] if n and n > 0 else self._payload


def _completion(score: float, rationale: str = "ok") -> bytes:
    content = json.dumps({"score": score, "rationale": rationale})
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _patch_transport(
    monkeypatch: pytest.MonkeyPatch, payload: bytes | Exception, sink: list[Any]
) -> None:
    def fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResp:
        sink.append(req)
        if isinstance(payload, Exception):
            raise payload
        return _FakeResp(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def _judge_metric(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "faithfulness",
        "evaluator_ref": "judge_score@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0.0, 1.0],
        "required_evidence": ["judge"],
        **overrides,
    }


def _write_dataset(root: Path) -> None:
    (root / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a"}) + "\n",
        encoding="utf-8",
    )


def _openai_judge_config(**overrides: Any) -> dict[str, Any]:
    return {
        "adapter": "openai_compatible",
        "endpoint": _ENDPOINT,
        "model": "judge-model",
        "credential_env": "EG_JUDGE_KEY",
        **overrides,
    }


# --------------------------------------------------------------------------- #
# _build_judge_model — selection, capability, lazy import, effect-time secret
# --------------------------------------------------------------------------- #


def test_build_selects_openai_model_with_measurement_capability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EG_JUDGE_KEY", "sk-secret")
    cfg = JudgeConfig.from_mapping(_openai_judge_config())
    model = _build_judge_model(cfg, tmp_path)
    assert model.capability is JudgeCapability.MEASUREMENT


def test_no_judge_run_does_not_import_the_openai_adapter() -> None:
    # AC: lazy construction so a no-judge run imports no live adapter. Importing the runner (or a
    # fake/command build) must not pull the OpenAI adapter module into sys.modules.
    sys.modules.pop("evalglass.adapters.judge_openai", None)
    import importlib

    importlib.reload(sys.modules["evalglass.harness.runner"])
    _build_judge_model(JudgeConfig.from_mapping({"adapter": "fake"}), Path("."))
    assert "evalglass.adapters.judge_openai" not in sys.modules


def test_declared_credential_absent_is_unavailable_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # AC3: a missing credential is a typed unavailable state, never a fabricated score.
    monkeypatch.delenv("EG_JUDGE_KEY", raising=False)
    cfg = JudgeConfig.from_mapping(_openai_judge_config())
    with pytest.raises(MissingPrerequisite):
        _build_judge_model(cfg, tmp_path)


def test_keyless_local_endpoint_builds_without_a_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = JudgeConfig.from_mapping(
        {
            "adapter": "openai_compatible",
            "endpoint": "http://127.0.0.1:8000/v1/chat/completions",
            "model": "local",
            "allow_insecure_loopback": True,
        }
    )
    model = _build_judge_model(cfg, tmp_path)
    assert model.capability is JudgeCapability.MEASUREMENT


# --------------------------------------------------------------------------- #
# End-to-end run_config — valid completion, non-scored failures, authority
# --------------------------------------------------------------------------- #


def _run_openai(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes | Exception,
    *,
    judge_overrides: dict[str, Any] | None = None,
    metric_overrides: dict[str, Any] | None = None,
    key: str | None = "sk-secret",
) -> tuple[Any, list[Any]]:
    _write_dataset(tmp_path)
    if key is not None:
        monkeypatch.setenv("EG_JUDGE_KEY", key)
    sink: list[Any] = []
    _patch_transport(monkeypatch, payload, sink)
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": _openai_judge_config(**(judge_overrides or {})),
        "metrics": [_judge_metric(**(metric_overrides or {}))],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    return record, sink


def test_valid_completion_produces_a_scored_judge_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, sink = _run_openai(tmp_path, monkeypatch, _completion(0.75))
    assert len(sink) == 1  # exactly one planned eligible request reached the adapter
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is ScoreStatus.SCORED
    assert score.value == pytest.approx(0.75)


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode("utf-8"),
        urllib.error.URLError("boom"),
        TimeoutError("slow"),
    ],
)
def test_provider_or_parse_failure_has_no_numeric_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes | Exception
) -> None:
    record, _sink = _run_openai(tmp_path, monkeypatch, payload)
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is not ScoreStatus.SCORED
    assert score.value is None


def test_real_openai_judge_is_uncalibrated_and_cannot_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AC: capability is MEASUREMENT, but with no calibration record the judge stays informational.
    record, _sink = _run_openai(
        tmp_path,
        monkeypatch,
        _completion(0.9),
        metric_overrides={
            "metric_status": "gating",
            "threshold_approval": "approved",
            "threshold": 0.5,
        },
    )
    authority = record.scorecard.authority["faithfulness"]
    assert authority.level is AuthorityLevel.INFORMATIONAL
    assert not authority.can_gate
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL


def test_calibrated_openai_judge_can_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The full authority path for the promoted adapter: a MEASUREMENT judge + a host calibration
    # record + an approved threshold makes the gate live (0.9 clears the approved 0.5) -> PASS.
    _write_dataset(tmp_path)
    monkeypatch.setenv("EG_JUDGE_KEY", "sk-secret")
    _patch_transport(monkeypatch, _completion(0.9), [])
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "faithfulness.json").write_text(
        json.dumps(
            {
                "calibration": {
                    "status": "calibrated",
                    "approver": "alice",
                    "rationale": "labels",
                    "variance_runs": 5,
                },
                "threshold": {
                    "value": 0.5,
                    "direction": "higher_is_better",
                    "variance": 0.05,
                    "approver": "alice",
                    "rationale": "p95",
                    "version": "1",
                },
            }
        ),
        encoding="utf-8",
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": _openai_judge_config(),
        "metrics": [
            _judge_metric(metric_status="gating", calibration="calibration/faithfulness.json")
        ],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    assert record.scorecard.authority["faithfulness"].can_gate
    assert record.scorecard.verdict.verdict is Verdict.PASS


def test_denied_egress_makes_no_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_dataset(tmp_path)
    monkeypatch.setenv("EG_JUDGE_KEY", "sk-secret")
    sink: list[Any] = []
    _patch_transport(monkeypatch, _completion(1.0), sink)
    raw: dict[str, Any] = {
        # forbidden data policy: the judge must never be called for this subject.
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "forbidden"}],
        "judge": _openai_judge_config(),
        "metrics": [_judge_metric()],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    assert sink == []  # egress checked before any serialization/network
    score = next(s for s in record.scores if s.metric == "faithfulness")
    assert score.status is not ScoreStatus.SCORED
    assert score.value is None


# --------------------------------------------------------------------------- #
# Secret safety — the credential never lands in any artifact
# --------------------------------------------------------------------------- #


def test_secret_is_sent_but_never_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-proj-TOPSECRET-do-not-persist"  # noqa: S105 — test fixture, not a real credential
    record, sink = _run_openai(tmp_path, monkeypatch, _completion(0.6), key=secret)
    # It DID authenticate the outgoing request…
    assert sink[0].headers.get("Authorization") == f"Bearer {secret}"
    # …but the secret appears in no persisted surface.
    blob = json.dumps(record.to_dict())
    assert secret not in blob
    assert "EG_JUDGE_KEY" not in blob
    prov = record.provenance.to_dict() if hasattr(record.provenance, "to_dict") else {}
    assert secret not in json.dumps(prov)
