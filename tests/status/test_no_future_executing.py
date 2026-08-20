"""EG-AT3-4 — no unshipped capability shown executing now (alignment plan §7.0, §7.2, ST-EXEC).

ST-EXEC-1 flags a sentence that pairs a deferred capability with a present-tense execution
verb (pulls / uploads / generates / queries / tunes / …) without an honest future marker.
ST-EXEC-2 proves no committed example artifact evidences a non-``now`` capability having run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.plugin.lexicons import deferred_keywords_in, has_execution_verb, has_future_marker
from tests.plugin.prose_scan import scan_capability_sentences
from tests.plugin.rendered_surfaces import audited_prose_files, example_artifacts

pytestmark = pytest.mark.public_surface

_FIXTURES = Path(__file__).parent / "fixtures"


def _executes_without_future_marker(sentence: str) -> bool:
    return has_execution_verb(sentence) and not has_future_marker(sentence)


# --------------------------------------------------------------------------- ST-EXEC-1


def test_no_deferred_capability_shown_executing_now() -> None:
    assert scan_capability_sentences(audited_prose_files(), _executes_without_future_marker) == []


def test_exec1_sensitivity_executing_langfuse_fires() -> None:
    found = scan_capability_sentences(
        [_FIXTURES / "exec_langfuse.md"], _executes_without_future_marker
    )
    assert found != []


def test_exec1_specificity_two_capabilities_flags_neither() -> None:
    """A now capability and a future-qualified one in one line must flag neither."""
    found = scan_capability_sentences(
        [_FIXTURES / "exec_two_caps.md"], _executes_without_future_marker
    )
    assert found == []


# --------------------------------------------------------------------------- ST-EXEC-2


def _deferred_ran(obj: Any) -> list[str]:
    """Recursively find any object marked ``status: ran`` whose lane name is a deferred capability.

    Binds the ``ran`` evidence to the *same* lane object, so a multi-lane artifact with a deferred
    lane ``skipped`` and a local lane ``ran`` is not falsely flagged.
    """
    found: list[str] = []
    if isinstance(obj, dict):
        name = obj.get("lane") or obj.get("name")
        if obj.get("status") == "ran" and isinstance(name, str):
            found += deferred_keywords_in(name)
        for value in obj.values():
            found += _deferred_ran(value)
    elif isinstance(obj, list):
        for item in obj:
            found += _deferred_ran(item)
    return found


def _evidences_deferred_execution(path: Path) -> list[str]:
    """The deferred lanes an artifact records as having ``ran``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return _deferred_ran(data)


def test_examples_never_evidence_a_deferred_capability_ran() -> None:
    offenders = [
        f"{path.name}:{keywords}"
        for path in example_artifacts()
        if (keywords := _evidences_deferred_execution(path))
    ]
    assert offenders == []


def test_exec2_sensitivity_fabricated_deferred_run_fires() -> None:
    assert _evidences_deferred_execution(_FIXTURES / "example_langfuse_ran.json") == ["langfuse"]


def test_exec2_specificity_deferred_skipped_with_local_ran_stays_quiet() -> None:
    """A deferred lane ``skipped`` next to a local lane ``ran`` is not deferred evidence."""
    assert _evidences_deferred_execution(_FIXTURES / "example_mixed_lanes.json") == []


def test_inflected_multiword_execution_verbs_are_caught() -> None:
    """The regex fix: inflected single- and multi-word run verbs all match (Codex P2)."""
    for phrase in ("pulls live", "uploads", "generates", "queries", "exports to", "connects to"):
        assert has_execution_verb(phrase), phrase
    assert not has_execution_verb("describes the scorecard")
