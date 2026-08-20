"""Shared provider-lane config + credential conventions (EG-R0-4; ADR 0033).

Provider connector configuration is explicit, fail-closed, and reviewable. The common option set —
endpoint, project, query, time window, limit, and credential **env-var references** — is parsed by
one shared validator so all three connectors behave identically:

- an unknown option key or a wrongly-typed value is a fail-closed setup error (a ``LaneError``
  subclass — the seam turns it into a ``BLOCKED`` lane result, never a crash or a score);
- credentials are env-var *references* (names), resolved from the environment only at lane time and
  never written to any persisted structure;
- the ``DataPolicy`` egress gate refuses ``forbidden``/``missing``/``unknown`` **before** any live
  call (egress-before-effects).
"""

from __future__ import annotations

import pytest

from evalglass.adapters._connector_boundary import (
    ConnectorConfigError,
    egress_gate,
    egress_permitted,
    parse_provider_options,
    resolve_credentials,
)
from evalglass.core import DataPolicy
from evalglass.harness.lanes import LaneError, LaneResult, LaneStatus

# --- option parsing (fail-closed) --------------------------------------------


def test_parse_good_options_round_trips() -> None:
    opts = parse_provider_options(
        {
            "endpoint": "  https://host  ",
            "project": "p1",
            "query": "tag=prod",
            "limit": 50,
            "start_time": "2026-01-01",
            "end_time": "2026-02-01",
            "credentials": {"api_key": "MY_API_KEY_ENV"},
        }
    )
    assert opts.endpoint == "https://host"
    assert opts.project == "p1"
    assert opts.limit == 50
    assert opts.credentials == {"api_key": "MY_API_KEY_ENV"}


def test_parse_empty_options_is_all_none() -> None:
    opts = parse_provider_options({})
    assert opts.endpoint is None
    assert opts.limit is None
    assert dict(opts.credentials) == {}


def test_unknown_option_key_fails_closed() -> None:
    with pytest.raises(ConnectorConfigError) as exc:
        parse_provider_options({"endpoint": "https://h", "nope": 1})
    assert "nope" in str(exc.value)


def test_config_error_is_a_lane_error_so_the_seam_blocks_it() -> None:
    # The seam catches (LaneError, TypeError, ValueError) → BLOCKED; a config error must be one.
    assert issubclass(ConnectorConfigError, LaneError)


def test_extra_keys_are_allowed_when_declared() -> None:
    opts = parse_provider_options(
        {"endpoint": "https://h", "session_id": "s"}, extra_keys=["session_id"]
    )
    assert opts.endpoint == "https://h"


@pytest.mark.parametrize("bad_limit", [0, -1, "10", 2.5, True])
def test_limit_must_be_a_positive_int(bad_limit: object) -> None:
    with pytest.raises(ConnectorConfigError):
        parse_provider_options({"limit": bad_limit})


@pytest.mark.parametrize("bad", ["", "   ", 5, ["x"]])
def test_string_options_must_be_non_empty_strings(bad: object) -> None:
    with pytest.raises(ConnectorConfigError):
        parse_provider_options({"endpoint": bad})


@pytest.mark.parametrize("bad_creds", [["a"], {"k": 1}, {"k": ""}, {1: "ENV"}, "ENV"])
def test_credentials_must_map_name_to_env_ref(bad_creds: object) -> None:
    with pytest.raises(ConnectorConfigError):
        parse_provider_options({"credentials": bad_creds})


def test_inline_credential_value_is_rejected_without_leaking_it() -> None:
    """A non-env-var-name value (what a pasted inline secret would be) is rejected — and the error
    never echoes the offending value, so a rejected secret can't leak into the diagnostic."""
    inline = "value with spaces and -dashes"  # not a valid env-var name → rejected
    with pytest.raises(ConnectorConfigError) as exc:
        parse_provider_options({"credentials": {"api_key": inline}})
    assert inline not in str(exc.value)


def test_blank_credential_key_is_rejected() -> None:
    with pytest.raises(ConnectorConfigError):
        parse_provider_options({"credentials": {"   ": "MY_ENV"}})


def test_non_mapping_options_fail_closed() -> None:
    with pytest.raises(ConnectorConfigError):
        parse_provider_options(["not", "a", "mapping"])


# --- egress gate (egress-before-effects) -------------------------------------


@pytest.mark.parametrize("policy", [DataPolicy.PERMITTED, DataPolicy.REDACTED])
def test_egress_permitted_only_for_permitted_and_redacted(policy: DataPolicy) -> None:
    assert egress_permitted(policy) is True
    assert egress_gate(policy, lane="x-trace", code="x_egress_forbidden") is None


@pytest.mark.parametrize("policy", [DataPolicy.FORBIDDEN, DataPolicy.MISSING, DataPolicy.UNKNOWN])
def test_egress_gate_blocks_non_egress_policy_before_any_call(policy: DataPolicy) -> None:
    assert egress_permitted(policy) is False
    blocked = egress_gate(policy, lane="x-trace", code="x_egress_forbidden")
    assert isinstance(blocked, LaneResult)
    assert blocked.status is LaneStatus.BLOCKED
    assert blocked.diagnostics[0].code == "x_egress_forbidden"
    assert policy.value in blocked.report


# --- credential resolution (refs in config, secrets only in memory) ----------


def test_resolve_credentials_reads_env_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_API_KEY_ENV", "resolved-value")
    monkeypatch.delenv("ABSENT_ENV", raising=False)
    resolved = resolve_credentials({"api_key": "MY_API_KEY_ENV", "missing": "ABSENT_ENV"})
    assert resolved == {"api_key": "resolved-value"}  # absent ref omitted, not crashed


def test_only_env_ref_names_are_in_config_never_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """The persisted config object holds env-var NAMES; the secret value lives only post-resolve."""
    monkeypatch.setenv("MY_API_KEY_ENV", "resolved-value")
    opts = parse_provider_options({"credentials": {"api_key": "MY_API_KEY_ENV"}})
    # What a run would persist (provenance/lane config) carries the NAME, never the secret.
    assert "resolved-value" not in repr(opts)
    assert opts.credentials["api_key"] == "MY_API_KEY_ENV"
    # The secret materializes only when explicitly resolved for the client call.
    assert resolve_credentials(opts.credentials)["api_key"] == "resolved-value"
