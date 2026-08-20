"""Annotation foundation: local import/export + authority fencing (EG-H3-4, EG-H3-5).

The annotation foundation is a real, stdlib-only LOCAL surface for host annotation records. It is a
harness service (never the Core) and a NON-lane surface that manufactures no authority:

* an annotation is an authority input ONLY when a host validation record backs it — missing, blank,
  whitespace, or non-string records never grant authority;
* the export is one-way and JSON-compatible (round-trips through import), fail-closed on a bad name
  or a symlinked destination;
* the surface exposes no approve/gate/certify/promote/tune/writeback/feedback verb, and an
  AnnotationImport carries no score/verdict/authority/can_gate/ci_should_fail attribute.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evalglass.harness import annotation as annotation_mod
from evalglass.harness.annotation import (
    AnnotationError,
    export_annotations,
    import_annotations,
)
from evalglass.harness.governance import AnnotationImport, GovernanceError

_FORBIDDEN_VERB = re.compile(r"approve|gate|certify|promote|tune|writeback|feedback", re.IGNORECASE)
_FORBIDDEN_ATTRS = ("score", "verdict", "authority", "can_gate", "ci_should_fail")


def _write_jsonl(path: Path, lines: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# EG-H3-4 — local import / export                                             #
# --------------------------------------------------------------------------- #
def test_export_then_import_round_trips(tmp_path: Path) -> None:
    records = [
        AnnotationImport("a1", "good", validation_record="host-validated-2026"),
        AnnotationImport("a2", {"label": "bad"}, validation_record=None),
    ]
    out = export_annotations(records, root=tmp_path, name="batch")
    assert out == tmp_path / "evals" / "annotations" / "batch.jsonl"
    reloaded = import_annotations(out)
    assert reloaded == records


def test_export_is_one_way_json_compatible(tmp_path: Path) -> None:
    out = export_annotations(
        [AnnotationImport("a1", 1, validation_record="r")], root=tmp_path, name="b"
    )
    # Every line is valid JSON; the export writes only the annotation tree, nothing host-owned.
    for line in out.read_text(encoding="utf-8").splitlines():
        json.loads(line)


@pytest.mark.parametrize(
    "record",
    [
        '{"value": "x", "validation_record": "r"}',  # missing annotation_id
        '{"annotation_id": "", "value": "x"}',  # blank annotation_id
        '{"annotation_id": "a1"}',  # missing value
        '{"annotation_id": "a1", "value": "x", "validation_record": 5}',  # non-string record
        "{not json",  # invalid JSON
        '["not", "an", "object"]',  # not a JSON object
    ],
)
def test_import_fails_closed_on_malformed(tmp_path: Path, record: str) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(record + "\n", encoding="utf-8")
    with pytest.raises(AnnotationError):
        import_annotations(path)


def test_export_fails_closed_on_non_finite_value(tmp_path: Path) -> None:
    """A non-finite annotation value (NaN/inf) is rejected before any write, so the export stays
    JSON-compatible and round-trippable; no partial artifact is left behind."""
    with pytest.raises(AnnotationError):
        export_annotations(
            [AnnotationImport("a1", float("nan"), validation_record="r")], root=tmp_path, name="b"
        )
    assert not (tmp_path / "evals" / "annotations" / "b.jsonl").exists()


def test_export_fails_closed_on_unsafe_name(tmp_path: Path) -> None:
    with pytest.raises(GovernanceError):
        export_annotations([], root=tmp_path, name="../evil")


def test_export_refuses_symlinked_target(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("host secret\n", encoding="utf-8")
    out_dir = tmp_path / "evals" / "annotations"
    out_dir.mkdir(parents=True)
    (out_dir / "b.jsonl").symlink_to(outside)
    with pytest.raises(GovernanceError):
        export_annotations([AnnotationImport("a1", 1)], root=tmp_path, name="b")
    assert outside.read_text(encoding="utf-8") == "host secret\n"


# --------------------------------------------------------------------------- #
# EG-H3-5 — authority fencing                                                 #
# --------------------------------------------------------------------------- #
def test_annotation_without_validation_record_is_not_authority(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "a.jsonl", [{"annotation_id": "a1", "value": "x"}])
    [record] = import_annotations(path)
    assert record.is_authority_input is False


@pytest.mark.parametrize("record_value", ["", "   ", "\t\n"])
def test_blank_or_whitespace_validation_record_is_not_authority(
    tmp_path: Path, record_value: str
) -> None:
    path = _write_jsonl(
        tmp_path / "a.jsonl",
        [{"annotation_id": "a1", "value": "x", "validation_record": record_value}],
    )
    [record] = import_annotations(path)
    assert record.is_authority_input is False


def test_typed_non_blank_validation_record_is_eligible_authority(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "a.jsonl",
        [{"annotation_id": "a1", "value": "x", "validation_record": "host-validated-2026"}],
    )
    [record] = import_annotations(path)
    assert record.is_authority_input is True


def test_surface_exposes_no_authority_verb() -> None:
    public = [n for n in dir(annotation_mod) if not n.startswith("_")]
    offenders = [n for n in public if _FORBIDDEN_VERB.search(n)]
    assert offenders == [], f"annotation surface exposes an authority verb: {offenders}"


def test_annotation_import_carries_no_authority_attribute() -> None:
    record = AnnotationImport("a1", "x", validation_record="r")
    present = [attr for attr in _FORBIDDEN_ATTRS if hasattr(record, attr)]
    assert present == [], f"AnnotationImport carries a forbidden attribute: {present}"
