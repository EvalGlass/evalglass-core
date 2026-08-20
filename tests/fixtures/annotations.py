"""F-5 — annotation-record fixtures (EG-AT0-4).

A sensitivity/specificity pair by construction: an annotation with no (or a
blank/whitespace) ``validation_record`` is **not** an authority input; one with a
real host record is. The runtime contract lives in
``evalglass.harness.governance.AnnotationImport``.
"""

from __future__ import annotations

from typing import Any

from evalglass.harness.governance import AnnotationImport


def make_annotation(
    *,
    annotation_id: str = "a1",
    value: Any = 1,
    validation_record: str | None = None,
) -> AnnotationImport:
    """Build an :class:`AnnotationImport`; ``validation_record`` toggles authority eligibility."""
    return AnnotationImport(
        annotation_id=annotation_id, value=value, validation_record=validation_record
    )


__all__ = ["make_annotation"]
