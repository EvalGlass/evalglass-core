"""Governance 1B — annotation authority needs a typed non-blank host record (EG-AT2-2).

Source: alignment test plan §6 Part 1B and §5.6 (with the GAP-5 fix).

An ``AnnotationImport`` is informational evidence unless a host supplies a real
``validation_record``. The contract is typed ``str | None`` (mypy-enforced), and at
runtime the authority check uses an explicit ``isinstance`` guard so a non-string
record is *rejected as not-authority* — never an ``AttributeError``, and never
silently coerced into a truthy string.

Pure, hermetic unit tests in a new file; the frozen canary ``test_governance.py``
stays byte-stable (AT1 FS-META).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from evalglass.harness.governance import AnnotationImport
from tests.fixtures.annotations import make_annotation

# Blank/empty/None records — all informational, never authority.
_BLANK_RECORDS: list[str | None] = ["", "   ", "\t", "\n", "\r\n", "  \t \n ", None]

# Non-string records (a hopeful caller bypassing the str|None type). The truthy ones
# (1, True, 1.5, object()) would crash the old ``and .strip()`` chain; the falsy ones
# (0, [], {}) short-circuit. All must resolve to *not-authority* without raising.
_NON_STRING_RECORDS: list[Any] = [1, 0, True, 1.5, [], {}, object()]


@pytest.mark.parametrize("record", _BLANK_RECORDS)
def test_blank_or_none_record_is_not_authority(record: str | None) -> None:
    annotation = AnnotationImport(annotation_id="a", value=1, validation_record=record)
    assert annotation.is_authority_input is False


@pytest.mark.parametrize("record", _NON_STRING_RECORDS)
def test_non_string_record_is_not_authority_and_does_not_crash(record: Any) -> None:
    """A non-string record is rejected as not-authority — no ``AttributeError``."""
    annotation = AnnotationImport(annotation_id="a", value=1, validation_record=record)
    assert annotation.is_authority_input is False


def test_real_host_validation_record_is_authority() -> None:
    """Specificity: a real host-supplied record makes the annotation an authority input."""
    annotation = AnnotationImport(
        annotation_id="a", value=1, validation_record="host:rev-1 approved"
    )
    assert annotation.is_authority_input is True
    # Via the F-5 fixture sensitivity/specificity pair.
    assert make_annotation(validation_record="host:rev-2").is_authority_input is True
    assert make_annotation(validation_record=None).is_authority_input is False
    assert make_annotation(validation_record="   ").is_authority_input is False


def test_authority_comes_only_from_the_record_field() -> None:
    """There is no method/property that manufactures authority absent a host record.

    The only difference between an informational annotation and an authority input is
    the host-owned ``validation_record`` value — nothing the annotation can do to
    itself promotes it.
    """
    informational = AnnotationImport(annotation_id="a", value=1)
    assert informational.is_authority_input is False
    promoted = AnnotationImport(annotation_id="a", value=1, validation_record="host:rev-1")
    assert promoted.is_authority_input is True


def test_to_dict_round_trips_json_with_and_without_record() -> None:
    without = AnnotationImport(annotation_id="a", value=1)
    assert json.loads(json.dumps(without.to_dict())) == without.to_dict()
    assert "validation_record" not in without.to_dict()

    with_record = AnnotationImport(
        annotation_id="a", value={"k": [1, 2]}, validation_record="host:1"
    )
    round_tripped = json.loads(json.dumps(with_record.to_dict()))
    assert round_tripped == with_record.to_dict()
    assert round_tripped["validation_record"] == "host:1"
