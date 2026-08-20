"""Annotation-workflow lane boundary + governed coverage (EG-AT4-8; EG-H3-4; plan §5.6, delta D5).

The annotation **foundation** ships in EG-H3 (local import/export of host records); the rich
annotation *UI* remains experimental and does not ship. AT2-2 (``test_governance_annotation.py``)
proves the typed ``str | None`` rejection (blank / whitespace / non-str → not authority, without a
crash). This slice covers the lane-shaped parts AT2 did not:

* the annotation surface is **one-way** — its only public methods are a bool authority *query* and
  a ``to_dict`` *export*; it exposes no approve/gate/promote/tune verb and no score/verdict field;
* an annotation **without a host record cannot serve as authority** — ``is_authority_input`` is the
  single authority hook and it is ``False`` without a record;
* the foundation is built as a **non-lane** governed surface — its ``eg_m5c.yaml`` row is
  ``covered`` with real ``m5c.annotation.*`` scenarios, yet no annotation lane is registered.

Pure, hermetic tests; a new sibling file so the frozen ``test_governance.py`` canary stays stable.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from evalglass.harness.governance import AnnotationImport
from evalglass.harness.lanes import built_in_lanes
from tests.fixtures.annotations import make_annotation

_COVERAGE = Path(__file__).resolve().parents[1] / "egts" / "coverage" / "eg_m5c.yaml"
_ANNOTATION_ROW = "EG-M5C-4"

#: Verbs an annotation surface must never expose — it informs, it never decides or mutates.
_AUTHORITY_VERBS = ("approve", "gate", "certify", "promote", "tune", "writeback", "feedback")
#: Fields/attributes an annotation must never carry.
_FORBIDDEN_ATTRS = ("score", "scores", "verdict", "authority", "can_gate", "ci_should_fail")


def test_annotation_without_record_is_not_authority() -> None:
    """Premise: no host ``validation_record`` → not an authority input (cf. AT2-2)."""
    assert make_annotation(validation_record=None).is_authority_input is False


def test_annotation_surface_is_one_way() -> None:
    """The only public methods are a bool query + an export; no authority/mutation verb exists."""
    public = [n for n in dir(AnnotationImport) if not n.startswith("_")]
    offenders = [n for n in public if any(verb in n.lower() for verb in _AUTHORITY_VERBS)]
    assert offenders == [], f"annotation surface exposes an authority/mutation verb: {offenders}"
    # The export is read-only and the type carries no decision field.
    assert "to_dict" in public
    field_names = {f.name for f in dataclasses.fields(AnnotationImport)}
    assert field_names == {"annotation_id", "value", "validation_record"}
    assert not field_names & set(_FORBIDDEN_ATTRS)


def test_annotation_is_authority_input_is_the_single_authority_hook() -> None:
    """Authority eligibility flows only through ``is_authority_input`` — and it gates on the record.

    A real host record flips it to True; nothing else on the type can grant authority.
    """
    assert (
        make_annotation(validation_record="approved-by:[email protected]").is_authority_input
        is True
    )
    assert make_annotation(validation_record=None).is_authority_input is False


def test_annotation_export_round_trip_is_json_compatible() -> None:
    """The one-way export is JSON-shaped and omits an absent record (no implied authority)."""
    exported = make_annotation(validation_record=None).to_dict()
    assert "validation_record" not in exported  # absent record is not implied present
    assert isinstance(exported, dict)


@pytest.mark.parametrize("record", ["", "   ", "\t", "\n", None, 1, 0, [], {}])
def test_annotation_without_real_record_cannot_gate(record: Any) -> None:
    """Sensitivity: blank / whitespace / non-str / falsy records are all not-authority, no crash."""
    assert make_annotation(validation_record=record).is_authority_input is False


def test_no_annotation_ui_lane_is_registered() -> None:
    """The UI is absent: no ``built_in_lanes()`` entry mentions annotation."""
    names = built_in_lanes().names()
    assert not any("annotation" in name for name in names), names


def test_annotation_capability_is_covered_as_a_non_lane() -> None:
    """The annotation row is ``covered`` with real ``m5c.annotation.*`` scenarios — the foundation
    is built — but it remains a non-lane (no annotation lane is registered, asserted above)."""
    rows = yaml.safe_load(_COVERAGE.read_text(encoding="utf-8"))["rows"]
    row = next(r for r in rows if r["product_ticket"] == _ANNOTATION_ROW)
    assert row["status"] == "covered"
    assert row.get("scenario_ids"), "a covered row needs real scenario ids"
    assert all(sid.startswith("m5c.annotation.") for sid in row["scenario_ids"])
