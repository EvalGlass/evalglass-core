"""Config-driven OpenAI-compatible judge selection — fail-closed parse + secret safety.

The host may now select a real OpenAI-compatible judge in ``judge:`` directly (no subprocess
wrapper). This proves the config boundary: every field parses or fails closed; the credential is
an environment-variable *name*, never an inline secret; the endpoint must be HTTPS unless an
explicit test-only loopback policy is set; and the gating provenance carries the judge's identity
(endpoint/model/decoding) but *never* the secret. ``fake``/``command`` stay byte-identical.
"""

from __future__ import annotations

from typing import Any

import pytest

from evalglass.core._validation import ContractError
from evalglass.harness.config import JudgeConfig

_OK: dict[str, Any] = {
    "adapter": "openai_compatible",
    "endpoint": "https://api.openai.com/v1/chat/completions",
    "model": "gpt-4o-mini",
    "credential_env": "OPENAI_API_KEY",
}


def _parse(**overrides: Any) -> JudgeConfig:
    return JudgeConfig.from_mapping({**_OK, **overrides})


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_openai_adapter_parses_with_defaults() -> None:
    cfg = _parse()
    assert cfg.adapter == "openai_compatible"
    assert cfg.endpoint == "https://api.openai.com/v1/chat/completions"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.credential_env == "OPENAI_API_KEY"
    # Conservative, bounded decoding/size defaults.
    assert cfg.max_input_chars > 0
    assert cfg.max_output_tokens > 0
    assert cfg.response_format == "json_object"
    assert cfg.allow_insecure_loopback is False


def test_openai_adapter_accepts_bounded_overrides() -> None:
    cfg = _parse(
        max_input_chars=1000,
        max_output_tokens=128,
        response_format="text",
        timeout_seconds=12.5,
    )
    assert cfg.max_input_chars == 1000
    assert cfg.max_output_tokens == 128
    assert cfg.response_format == "text"
    assert cfg.timeout_seconds == 12.5


def test_credential_env_is_optional_for_keyless_local_endpoints() -> None:
    # A local OpenAI-compatible server may need no key; the credential reference is optional.
    cfg = JudgeConfig.from_mapping(
        {
            "adapter": "openai_compatible",
            "endpoint": "https://localhost:8000/v1/chat/completions",
            "model": "local-model",
        }
    )
    assert cfg.credential_env is None


# --------------------------------------------------------------------------- #
# Fail-closed: required identity
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("missing", ["endpoint", "model"])
def test_missing_required_identity_is_a_setup_error(missing: str) -> None:
    data = {k: v for k, v in _OK.items() if k != missing}
    with pytest.raises(ContractError):
        JudgeConfig.from_mapping(data)


def test_non_https_endpoint_is_refused() -> None:
    with pytest.raises(ContractError):
        _parse(endpoint="http://api.openai.com/v1/chat/completions")


def test_unknown_scheme_endpoint_is_refused() -> None:
    with pytest.raises(ContractError):
        _parse(endpoint="ftp://api.openai.com/v1")


# --------------------------------------------------------------------------- #
# Loopback policy (test-only, explicit)
# --------------------------------------------------------------------------- #


def test_plaintext_loopback_needs_the_explicit_policy() -> None:
    with pytest.raises(ContractError):
        _parse(endpoint="http://127.0.0.1:8000/v1/chat/completions")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:8000/v1/chat/completions",
        "http://localhost:8000/v1/chat/completions",
        "http://[::1]:8000/v1/chat/completions",
    ],
)
def test_plaintext_loopback_allowed_only_under_explicit_policy(endpoint: str) -> None:
    cfg = _parse(endpoint=endpoint, allow_insecure_loopback=True)
    assert cfg.endpoint == endpoint


def test_loopback_policy_does_not_permit_a_public_plaintext_endpoint() -> None:
    # The policy is loopback-only: it must never green-light plaintext egress to the internet.
    with pytest.raises(ContractError):
        _parse(endpoint="http://api.openai.com/v1/chat/completions", allow_insecure_loopback=True)


# --------------------------------------------------------------------------- #
# Secret safety
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [
        "sk-proj-abc123DEFsecretlivetoken",  # looks like a real key, not a name
        "my api key",  # spaces
        "lowercase_name",  # env var names are upper-case; reject to avoid a pasted secret
        "OPENAI-API-KEY",  # hyphen is not a valid env identifier
    ],
)
def test_credential_env_rejects_anything_that_is_not_an_env_var_name(value: str) -> None:
    with pytest.raises(ContractError):
        _parse(credential_env=value)


def test_provenance_never_contains_the_credential_reference_or_a_secret() -> None:
    cfg = _parse(credential_env="OPENAI_API_KEY")
    prov = cfg.provenance()
    flat = repr(prov)
    assert "OPENAI_API_KEY" not in flat
    assert "credential" not in flat
    assert "api_key" not in flat
    # But the score-determining identity (endpoint + model) IS present, so a swap breaks comparison.
    assert prov["endpoint"] == cfg.endpoint
    assert prov["model"] == cfg.model
    assert prov["adapter"] == "openai_compatible"


def test_endpoint_or_model_change_changes_provenance() -> None:
    base = _parse().provenance()
    assert _parse(model="gpt-4o").provenance() != base
    assert _parse(endpoint="https://openrouter.ai/api/v1/chat/completions").provenance() != base


# --------------------------------------------------------------------------- #
# Headers allowlist (non-secret only)
# --------------------------------------------------------------------------- #


def test_non_secret_headers_pass_through() -> None:
    cfg = _parse(headers={"HTTP-Referer": "https://example.com", "X-Title": "evalglass"})
    assert dict(cfg.headers) == {"HTTP-Referer": "https://example.com", "X-Title": "evalglass"}


@pytest.mark.parametrize("name", ["Authorization", "authorization", "x-api-key", "Cookie"])
def test_secret_bearing_header_names_are_refused(name: str) -> None:
    # Credentials must flow through credential_env, never a raw header value in host config.
    with pytest.raises(ContractError):
        _parse(headers={name: "Bearer leaked"})


# --------------------------------------------------------------------------- #
# Bounded decoding validation + unknown keys
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["max_input_chars", "max_output_tokens"])
@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_bounds_are_refused(field: str, bad: int) -> None:
    with pytest.raises(ContractError):
        _parse(**{field: bad})


def test_unknown_response_format_is_refused() -> None:
    with pytest.raises(ContractError):
        _parse(response_format="yaml")


def test_unknown_key_is_refused() -> None:
    with pytest.raises(ContractError):
        _parse(temperature=0.7)


# --------------------------------------------------------------------------- #
# Backward compatibility: fake / command provenance byte-identical
# --------------------------------------------------------------------------- #


def test_fake_provenance_is_unchanged() -> None:
    cfg = JudgeConfig.from_mapping({"adapter": "fake", "default_value": 0.8})
    assert cfg.provenance() == {"adapter": "fake", "default_value": 0.8}


def test_command_provenance_is_unchanged() -> None:
    cfg = JudgeConfig.from_mapping({"adapter": "command", "command": ["./judge.sh"]})
    assert cfg.provenance() == {"adapter": "command", "default_value": None}
