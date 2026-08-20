"""FS-SNAP-2 — freeze the RunRecord JSON schema (EG-AT1 Slice 2, EG-AT1-2).

Freezes the RunRecord key structure, pins provenance to the ten required
dimensions, and asserts that every runner-stamped Score carries subject identity
(``example_id`` + ``unit_id``) while a hand-built identity-less Score still
round-trips. A present-but-malformed ``comparable`` block must fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import ContractError
from evalglass.core.results import RunRecord
from evalglass.core.scores import Score, ScoreStatus, Validity
from tests.scorecard_factory import informational_record

_SNAP = Path(__file__).parent / "_snapshots"


def _load(name: str) -> dict[str, Any]:
    data = json.loads((_SNAP / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.public_surface
def test_runrecord_to_dict_keyset_frozen(tmp_path: Path) -> None:
    record = informational_record(tmp_path).to_dict()
    keys = _load("runrecord_keys.json")
    top = set(record)
    assert set(keys["required"]) <= top
    assert top <= set(keys["required"]) | set(keys["optional"])
    assert sorted(record["provenance"]["dimensions"]) == keys["provenance_dimensions"]


@pytest.mark.public_surface
def test_runner_stamped_scores_carry_subject_identity(tmp_path: Path) -> None:
    record = informational_record(tmp_path).to_dict()
    keys = _load("runrecord_keys.json")
    assert record["scores"], "expected at least one stamped score"
    required = set(keys["score_entry_required"])
    allowed = required | set(keys["score_entry_optional"])
    for score in record["scores"]:
        assert "example_id" in score
        assert "unit_id" in score
        sk = set(score)
        assert required <= sk <= allowed


@pytest.mark.public_surface
def test_identityless_score_roundtrips_without_keys() -> None:
    score = Score(
        metric="m",
        value=1.0,
        status=ScoreStatus.SCORED,
        validity=Validity.VALID,
        evaluator_version="x@1",
    )
    data = score.to_dict()
    assert "example_id" not in data
    assert "unit_id" not in data
    assert Score.from_dict(data) == score


@pytest.mark.public_surface
def test_malformed_comparable_block_fails_closed(tmp_path: Path) -> None:
    data = informational_record(tmp_path).to_dict()
    data["comparable"] = "not-a-mapping"
    with pytest.raises(ContractError):
        RunRecord.from_dict(data)
