"""EG-AT3-6 — view --by-call is now; stale wording fails (alignment plan §7.3 ST-VOCAB-5, §8.10).

``view --by-call`` ships now (the F1 artifact-shape gate is green). Current README / skill /
runbook surfaces must not present it as gated/deferred/declining, and the by-call reader groups
scores by explicit subject identity — never by list order, and never by guessing when identity
is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.egts.checkers import CheckerError, group_scores_by_subject
from tests.plugin.lexicons import BY_CALL_STALE_PATTERNS
from tests.plugin.prose_scan import logical_blocks
from tests.plugin.rendered_surfaces import audited_prose_files
from tests.scorecard_factory import informational_record

pytestmark = pytest.mark.public_surface

_FIXTURES = Path(__file__).parent / "fixtures"


def _scan_stale_by_call(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        for start, block in logical_blocks(path.read_text(encoding="utf-8")):
            lowered = block.lower()
            if "by-call" in lowered and any(p in lowered for p in BY_CALL_STALE_PATTERNS):
                findings.append(f"{path.name}:{start}")
    return findings


# --------------------------------------------------------------------------- ST-VOCAB-5


def test_no_current_surface_presents_by_call_as_stale() -> None:
    assert _scan_stale_by_call(audited_prose_files()) == []


def test_stale_by_call_wording_is_detected() -> None:
    assert _scan_stale_by_call([_FIXTURES / "stale_by_call.md"]) != []


# --------------------------------------------------------------------------- §8.10 grouping


def test_by_call_groups_scores_by_explicit_subject_identity(tmp_path: Path) -> None:
    record: dict[str, Any] = informational_record(tmp_path).to_dict()
    grouped = group_scores_by_subject(record)
    assert grouped, "expected at least one subject bucket"
    scores = record["scores"]
    assert isinstance(scores, list)
    assert sum(len(bucket) for bucket in grouped.values()) == len(scores)


def test_old_runrecord_without_identity_refuses_guessed_grouping(tmp_path: Path) -> None:
    record: dict[str, Any] = informational_record(tmp_path).to_dict()
    scores = record["scores"]
    assert isinstance(scores, list)
    assert scores
    scores[0].pop("example_id", None)  # an old artifact lacking subject identity
    with pytest.raises(CheckerError):
        group_scores_by_subject(record)
