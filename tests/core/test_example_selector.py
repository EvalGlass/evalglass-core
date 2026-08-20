"""Per-metric example selector (EG-V02-4 / K2).

A metric may declare it applies only to a subset of examples, matched on the example's own
``metadata`` (host-declared keys — domain-neutral). This lets one run of a multi-call-site suite
score each metric against only its own call site's records instead of every example. The selector
is fail-closed (absent key → no match) and always matches a run-integrity example so an
incomplete-input run still blocks an active gate.
"""

from __future__ import annotations

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.contracts import EvalUnit, Example, UnitKind
from evalglass.core.selector import INTEGRITY_METADATA_KEY, ExampleSelector

_UNIT = EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1")


def _ex(metadata: dict[str, object]) -> Example:
    return Example(example_id="e", input="i", output={}, unit=_UNIT, metadata=metadata)


def test_matches_when_all_constraints_satisfied() -> None:
    sel = ExampleSelector(constraints={"workflow": ("extract",)})
    assert sel.matches(_ex({"workflow": "extract"}))
    assert not sel.matches(_ex({"workflow": "summarise"}))


def test_absent_key_is_no_match_fail_closed() -> None:
    sel = ExampleSelector(constraints={"workflow": ("extract",)})
    assert not sel.matches(_ex({"other": "extract"}))
    assert not sel.matches(_ex({}))


def test_value_may_be_one_of_several() -> None:
    sel = ExampleSelector(constraints={"workflow": ("a", "b")})
    assert sel.matches(_ex({"workflow": "a"}))
    assert sel.matches(_ex({"workflow": "b"}))
    assert not sel.matches(_ex({"workflow": "c"}))


def test_all_constraints_must_hold() -> None:
    sel = ExampleSelector(constraints={"workflow": ("x",), "tier": ("prod",)})
    assert sel.matches(_ex({"workflow": "x", "tier": "prod"}))
    assert not sel.matches(_ex({"workflow": "x", "tier": "dev"}))


def test_integrity_example_always_matches() -> None:
    # A run-integrity example (e.g. the route-error guard) must be scored by every metric
    # regardless of the selector, so incomplete input still blocks an active gate.
    sel = ExampleSelector(constraints={"workflow": ("never",)})
    assert sel.matches(_ex({INTEGRITY_METADATA_KEY: True}))


def test_unhashable_metadata_value_is_no_match_not_crash() -> None:
    sel = ExampleSelector(constraints={"workflow": ("a",)})
    assert not sel.matches(_ex({"workflow": ["a"]}))  # list value != scalar "a", no crash


def test_round_trip() -> None:
    sel = ExampleSelector(constraints={"workflow": ("a", "b"), "tier": ("prod",)})
    assert ExampleSelector.from_dict(sel.to_dict()) == sel


# --- fail-closed construction (negative controls) ---------------------------


def test_empty_constraints_rejected() -> None:
    with pytest.raises(ContractError):
        ExampleSelector(constraints={})


def test_bad_constraint_key_or_values_rejected() -> None:
    with pytest.raises(ContractError):
        ExampleSelector(constraints={"": ("a",)})
    with pytest.raises(ContractError):
        ExampleSelector(constraints={"k": ()})  # empty allowed tuple


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(ContractError):
        ExampleSelector.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]
