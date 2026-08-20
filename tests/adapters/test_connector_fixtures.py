"""Provider stub payload fixtures + mapping contract (EG-R0-7; ADR 0033).

Each connector's *required-tier* proof must be deterministic and hermetic before the real SDK
adapter merges. This slice ships one fixture family per provider (Langfuse / Phoenix / LangSmith) —
provider-native payloads with the variants a connector must handle — plus a shared mapping contract
(``fixtures/connectors/MAPPING.md``) naming which native field becomes ``trace_id`` / ``unit_id`` /
``behavior`` / ``metadata`` / ``timing``.

This guard validates the fixtures and the contract (it does not run a connector — the adapters land
in EG-R1…R3 and assert their normalized output equals each fixture's ``expected``):

- every fixture is plain JSON, loadable without a provider SDK installed;
- each family carries the required variants (good, vendor_wrapper, malformed, missing_field, empty)
  plus the declared ``expected`` normalized output;
- the ``vendor_wrapper`` payload actually contains the vendor wrapper keys a connector must drop;
- the ``expected`` output carries ``trace_id``/``unit_id``/``behavior`` and contains **no** vendor
  wrapper key (no vendor object leaks past the boundary);
- the mapping contract names every provider and every target field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "connectors"
_PROVIDERS = ("langfuse", "phoenix", "langsmith")
_REQUIRED_VARIANTS = ("good", "vendor_wrapper", "malformed", "missing_field", "empty", "expected")
_TARGET_FIELDS = ("trace_id", "unit_id", "behavior", "metadata", "timing")


def _family(provider: str) -> dict[str, Any]:
    data = json.loads((_FIXTURES / f"{provider}.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _all_keys(obj: Any) -> set[str]:
    """Every mapping key anywhere in a nested structure (so a wrapper key is matched as a key, not
    as an incidental substring of a legitimate field like ``metadata``)."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _all_keys(item)
    return keys


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_fixture_family_has_all_variants(provider: str) -> None:
    family = _family(provider)
    for key in (*_REQUIRED_VARIANTS, "vendor_wrapper_keys"):
        assert key in family, f"{provider} fixture is missing the {key!r} variant"
    assert family["vendor_wrapper_keys"], f"{provider} declares no vendor wrapper keys to drop"


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_malformed_variant_is_not_valid_json(provider: str) -> None:
    """The malformed fixture is a raw string a connector must convert to a Diagnostic, not parse."""
    malformed = _family(provider)["malformed"]
    assert isinstance(malformed, str)
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed)


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_vendor_wrapper_payload_contains_the_keys_to_drop(provider: str) -> None:
    family = _family(provider)
    present = _all_keys(family["vendor_wrapper"])
    for key in family["vendor_wrapper_keys"]:
        assert key in present, f"{provider} vendor_wrapper fixture omits the wrapper key {key!r}"


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_expected_output_is_normalized_and_vendor_free(provider: str) -> None:
    family = _family(provider)
    expected = family["expected"]
    assert isinstance(expected, list)
    assert expected, f"{provider} declares no expected output"
    leaked = _all_keys(expected) & set(family["vendor_wrapper_keys"])
    assert not leaked, f"{provider} expected output leaks vendor wrapper key(s): {sorted(leaked)}"
    for entry in expected:
        # Contract shape: an EvalUnit (unit_id + kind=call + trace_id) plus the envelope behavior,
        # with timing INSIDE behavior — exactly what a connector's TraceUnit emits (not a flattened
        # projection). The connector-uniform envelope fields (source, data_policy, provenance) are
        # asserted by each connector test, not per-fixture (see MAPPING.md).
        unit = entry.get("unit", {})
        assert unit.get("trace_id"), f"{provider} expected unit has no trace_id"
        assert unit.get("unit_id"), f"{provider} expected unit has no unit_id"
        assert unit.get("kind") == "call", f"{provider} expected unit kind must be 'call'"
        behavior = entry.get("behavior")
        assert isinstance(behavior, dict)
        assert behavior.get("output") is not None, (
            f"{provider} expected entry has no behavior output"
        )
        if "timing" in behavior:
            # Timing lives inside behavior with the shared map_span keys (start_time / end_time).
            assert {"start_time", "end_time"} <= set(behavior["timing"]), (
                f"{provider} timing keys must be start_time/end_time inside behavior"
            )


def test_mapping_contract_names_every_provider_and_field() -> None:
    contract = (_FIXTURES / "MAPPING.md").read_text(encoding="utf-8").lower()
    for provider in _PROVIDERS:
        assert provider in contract, f"the mapping contract does not name {provider}"
    for field in _TARGET_FIELDS:
        assert field in contract, f"the mapping contract does not name the target field {field!r}"
