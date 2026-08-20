"""Annotation foundation (EG-H3-4; ADR 0021; alignment plan §5.5, delta D5).

A real, stdlib-only **local** import/export surface for host annotation records. It is a harness
service (never the Core) and a **non-lane** surface that manufactures no authority:

- **An annotation is an authority input only with a host validation record.** Missing, blank,
  whitespace, or non-string records never grant authority (the
  :class:`~evalglass.harness.governance.AnnotationImport` invariant). This module writes no
  threshold approval or metric status, and exposes no approve/gate/certify/promote/tune/writeback/
  feedback verb.
- **Local + one-way.** :func:`import_annotations` reads a JSONL file into typed records, fail-closed
  on malformed input; :func:`export_annotations` serializes records to ``evals/annotations/`` as a
  one-way, JSON-compatible artifact (symlink-refused, root-bounded). No network; stdlib only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from evalglass.harness._safe_fs import assert_within_root, refuse_symlinks, safe_name
from evalglass.harness.governance import AnnotationImport

_ANNOTATIONS_SUBDIR = ("evals", "annotations")


class AnnotationError(ValueError):
    """A malformed annotation import — fail closed (never a silent drop or coerced authority)."""


def _reject_constant(token: str) -> float:
    raise AnnotationError(f"non-finite JSON constant not allowed: {token}")


def import_annotations(path: Path) -> list[AnnotationImport]:
    """Read a local annotation JSONL into typed :class:`AnnotationImport` records (fail-closed).

    Each non-blank line must be a JSON object with a non-empty string ``annotation_id`` and a
    ``value``; ``validation_record`` is optional but, when present, must be a string (a non-string
    record is malformed input, not a silently-not-authority value).
    """
    records: list[AnnotationImport] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line, parse_constant=_reject_constant)
        except ValueError as exc:
            raise AnnotationError(f"annotations line {lineno}: invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AnnotationError(f"annotations line {lineno}: each record must be a JSON object")
        annotation_id = data.get("annotation_id")
        if not isinstance(annotation_id, str) or not annotation_id.strip():
            raise AnnotationError(
                f"annotations line {lineno}: 'annotation_id' must be a non-empty string"
            )
        if "value" not in data:
            raise AnnotationError(f"annotations line {lineno}: 'value' is required")
        validation_record = data.get("validation_record")
        if validation_record is not None and not isinstance(validation_record, str):
            raise AnnotationError(
                f"annotations line {lineno}: 'validation_record' must be a string or null"
            )
        records.append(
            AnnotationImport(
                annotation_id=annotation_id,
                value=data["value"],
                validation_record=validation_record,
            )
        )
    return records


def export_annotations(records: Sequence[AnnotationImport], *, root: Path, name: str) -> Path:
    """Serialize records to ``evals/annotations/<name>.jsonl`` one-way (fail-closed, root-bounded).

    Refuses a blank/unsafe ``name`` or a symlinked destination; writes only the annotation artifact,
    never host-owned truth or any authority record.
    """
    safe = safe_name(name, kind="annotation file name")
    out_dir = root.joinpath(*_ANNOTATIONS_SUBDIR)
    path = out_dir / f"{safe}.jsonl"
    # Serialize BEFORE any write so a non-JSON-compatible value (a non-finite number, which
    # ``json.dumps`` would otherwise emit as NaN/Infinity and ``import_annotations`` would reject)
    # fails closed and never leaves a half-written, non-round-trippable artifact.
    try:
        payload = "".join(
            json.dumps(record.to_dict(), sort_keys=True, allow_nan=False) + "\n"
            for record in records
        )
    except ValueError as exc:
        raise AnnotationError(f"annotation value is not JSON-compatible: {exc}") from exc
    refuse_symlinks(root, [*_ANNOTATIONS_SUBDIR, f"{safe}.jsonl"])
    assert_within_root(root, path)
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return path
