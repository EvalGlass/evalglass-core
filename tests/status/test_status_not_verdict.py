"""EG-AT3-7 — capability status is not a verdict / score status / validity (§7.5 ST-NOTVERDICT).

The capability statuses now/next/planned/experimental are a roadmap axis; they must be provably
disjoint from every runtime-outcome enum (Verdict, ScoreStatus, Validity, ci_should_fail), never
appear as a scorecard verdict-class value, and never be applied to a run-outcome subject in prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from evalglass.core.scores import ScoreStatus, Validity
from evalglass.core.verdict import Verdict
from evalglass.harness.lanes import LaneStatus, Maturity
from tests.plugin.lexicons import (
    CAPABILITY_SUBJECT_TERMS,
    RUN_OUTCOME_TERMS,
    STATUS_WORDS,
    VERDICT_LABEL_WORDS,
)
from tests.plugin.prose_scan import logical_blocks
from tests.plugin.rendered_surfaces import audited_prose_files
from tests.plugin.status_registry import CapabilityStatus
from tests.scorecard_factory import informational_record

_FIXTURES = Path(__file__).parent / "fixtures"

_STATUS_TOKENS = {s.value for s in CapabilityStatus}
_VERDICT = {v.value for v in Verdict}
_SCORE = {s.value for s in ScoreStatus}
_VALIDITY = {v.value for v in Validity}
_OUTCOME_TOKENS = _VERDICT | _SCORE | _VALIDITY | {"ci_should_fail"}

# Direction A — a capability-status word modifies a run-outcome subject ("this run is experimental"
# / "an experimental verdict"). "now" is excluded — too common a plain English word to scan safely.
_STATUS_ALT = "|".join(sorted(STATUS_WORDS - {"now"}))
_OUTCOME_ALT = "|".join(sorted(RUN_OUTCOME_TERMS))
_STATUS_ON_OUTCOME = re.compile(
    rf"\b(?:{_OUTCOME_ALT})\b[^.;!]{{0,24}}?\b(?:is|was|becomes|are)\b[^.;!]{{0,12}}?\b(?:{_STATUS_ALT})\b"
    rf"|\b(?:{_STATUS_ALT})\b\s+(?:{_OUTCOME_ALT})\b",
    re.IGNORECASE,
)

# Direction B — a verdict word labels a capability subject ("the dashboard lane is fail").
_SUBJECT_ALT = "|".join(sorted(CAPABILITY_SUBJECT_TERMS))
_VERDICT_ALT = "|".join(sorted(VERDICT_LABEL_WORDS))
_VERDICT_ON_CAPABILITY = re.compile(
    rf"\b(?:{_SUBJECT_ALT})\b[^.;!]{{0,24}}?\b(?:is|was|becomes|are)\b[^.;!]{{0,12}}?\b(?:{_VERDICT_ALT})\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- ST-NOTVERDICT-1 / 3


@pytest.mark.core_isolation
def test_capability_status_disjoint_from_runtime_outcome_enums() -> None:
    assert _STATUS_TOKENS.isdisjoint(_VERDICT)
    assert _STATUS_TOKENS.isdisjoint(_SCORE)
    assert _STATUS_TOKENS.isdisjoint(_VALIDITY)
    assert _STATUS_TOKENS.isdisjoint({"ci_should_fail"})
    # The product-side Maturity enum (the one src capability status) is likewise disjoint.
    assert {m.value for m in Maturity} == _STATUS_TOKENS
    assert _STATUS_TOKENS.isdisjoint({s.value for s in LaneStatus})
    assert len(Verdict) == 4


@pytest.mark.public_surface
def test_no_scorecard_verdict_class_field_carries_a_status_token(tmp_path: Path) -> None:
    record = informational_record(tmp_path).to_dict()
    scorecard = record.get("scorecard", record)
    assert isinstance(scorecard, dict)
    verdict = scorecard["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] not in _STATUS_TOKENS
    for entry in scorecard["authority"].values():
        assert entry["level"] not in _STATUS_TOKENS


@pytest.mark.public_surface
def test_planned_as_a_verdict_member_is_rejected() -> None:
    """Negative control: a capability status is not a constructible Verdict."""
    with pytest.raises(ValueError, match="planned"):
        Verdict("planned")


# --------------------------------------------------------------------------- ST-NOTVERDICT-2


def _scan_status_verdict_misuse(paths: list[Path]) -> list[str]:
    """Bidirectional: a status word on a run outcome, or a verdict word on a capability."""
    findings: list[str] = []
    for path in paths:
        for start, block in logical_blocks(path.read_text(encoding="utf-8")):
            if _STATUS_ON_OUTCOME.search(block) or _VERDICT_ON_CAPABILITY.search(block):
                findings.append(f"{path.name}:{start}")
    return findings


def test_no_run_outcome_or_capability_is_mislabelled() -> None:
    assert _scan_status_verdict_misuse(audited_prose_files()) == []


def test_notverdict2_sensitivity_status_on_a_run_fires() -> None:
    assert _scan_status_verdict_misuse([_FIXTURES / "status_as_verdict.md"]) != []


def test_notverdict2_sensitivity_verdict_on_a_capability_fires() -> None:
    assert _scan_status_verdict_misuse([_FIXTURES / "verdict_as_label.md"]) != []


def test_notverdict2_specificity_correct_usage_stays_quiet() -> None:
    # "The lane is experimental; this run's verdict is informational" — both correct.
    assert _scan_status_verdict_misuse([_FIXTURES / "status_used_correctly.md"]) == []
