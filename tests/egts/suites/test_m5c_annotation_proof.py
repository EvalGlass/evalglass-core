"""EGTS-M5C-4 — annotation foundation proof (Route Proof, Trust Proof).

Proves the real product annotation foundation (EG-H3) over real imported records:

* ``m5c.annotation.no_record_no_authority`` — an annotation without a validation record is not an
  authority input;
* ``m5c.annotation.typed_validation_record`` — only a typed, non-blank host validation record makes
  an annotation eligible to inform authority (blank/whitespace/missing never do);
* ``m5c.annotation.no_self_approval`` — the surface exposes no approve/gate/certify/promote/tune/
  writeback/feedback verb, and an annotation carries no score/verdict/authority field, so labels
  can never approve themselves.

The export is one-way and JSON-compatible (round-trips). Scenario ids map to EG-M5C-4; annotation
remains experimental (foundation only, no rich UI). The full acceptance pack is rebuilt in EG-H5-4.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evalglass.harness import annotation as annotation_mod
from evalglass.harness.annotation import export_annotations, import_annotations
from evalglass.harness.governance import AnnotationImport

_FORBIDDEN_VERB = re.compile(r"approve|gate|certify|promote|tune|writeback|feedback", re.IGNORECASE)
_FORBIDDEN_ATTRS = ("score", "verdict", "authority", "can_gate", "ci_should_fail")


def _import_one(tmp_path: Path, record: dict[str, object]) -> AnnotationImport:
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    [imported] = import_annotations(path)
    return imported


def test_m5c_annotation_no_record_no_authority(tmp_path: Path) -> None:
    """m5c.annotation.no_record_no_authority — no validation record => not an authority input."""
    record = _import_one(tmp_path, {"annotation_id": "a1", "value": "good"})
    assert record.is_authority_input is False


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_m5c_annotation_blank_record_is_not_authority(tmp_path: Path, blank: str) -> None:
    record = _import_one(
        tmp_path, {"annotation_id": "a1", "value": "x", "validation_record": blank}
    )
    assert record.is_authority_input is False


def test_m5c_annotation_typed_validation_record(tmp_path: Path) -> None:
    """m5c.annotation.typed_validation_record — a typed, non-blank host record makes the annotation
    eligible to inform authority."""
    record = _import_one(
        tmp_path, {"annotation_id": "a1", "value": "x", "validation_record": "host-validated-2026"}
    )
    assert record.is_authority_input is True


def test_m5c_annotation_no_self_approval() -> None:
    """m5c.annotation.no_self_approval — no authority verb on the surface, no authority field on the
    record: a label can never approve itself."""
    public = [n for n in dir(annotation_mod) if not n.startswith("_")]
    assert [n for n in public if _FORBIDDEN_VERB.search(n)] == []
    record = AnnotationImport("a1", "x", validation_record="r")
    assert [attr for attr in _FORBIDDEN_ATTRS if hasattr(record, attr)] == []


def test_m5c_annotation_export_is_one_way_and_round_trips(tmp_path: Path) -> None:
    records = [AnnotationImport("a1", "good", validation_record="r"), AnnotationImport("a2", 2)]
    out = export_annotations(records, root=tmp_path, name="batch")
    assert out == tmp_path / "evals" / "annotations" / "batch.jsonl"
    assert import_annotations(out) == records
