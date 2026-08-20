"""FS-SNAP-1 — freeze the Scorecard JSON schema (EG-AT1 Slice 2, EG-AT1-2).

The Scorecard is a primary machine artifact (CLAUDE.md §4 #8). This guard freezes
its serialized key structure against a committed contract and reasserts the
spine's hardest rule at its serialization boundary: a non-scored status can never
carry ``0.0`` (an invalid/blocked measurement is not a low score).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import ContractError, Scorecard
from evalglass.core.scores import Score, ScoreStatus, Validity
from tests.scorecard_factory import informational_scorecard

_SNAP = Path(__file__).parent / "_snapshots"


def _load(name: str) -> dict[str, Any]:
    data = json.loads((_SNAP / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.public_surface
def test_scorecard_to_dict_keyset_frozen(tmp_path: Path) -> None:
    payload = informational_scorecard(tmp_path).to_dict()
    keys = _load("scorecard_keys.json")
    top = set(payload)
    assert set(keys["required"]) <= top, f"missing required scorecard keys: {keys['required']}"
    assert top <= set(keys["required"]) | set(keys["optional"]), f"unexpected top-level key: {top}"
    assert sorted(payload["verdict"]) == keys["verdict"]
    for entry in payload["authority"].values():
        assert sorted(entry) == keys["authority_entry"]
    for metric in payload["metrics"]:
        mk = set(metric)
        assert set(keys["metric_entry_required"]) <= mk
        assert mk <= set(keys["metric_entry_required"]) | set(keys["metric_entry_optional"])


@pytest.mark.public_surface
def test_scorecard_roundtrips(tmp_path: Path) -> None:
    sc = informational_scorecard(tmp_path)
    assert Scorecard.from_dict(sc.to_dict()) == sc


@pytest.mark.public_surface
def test_non_scored_status_never_serializes_0_0() -> None:
    """A blocked Score with value 0.0 is rejected at construction — before any dict."""
    with pytest.raises(ContractError):
        Score(
            metric="m",
            value=0.0,
            status=ScoreStatus.BLOCKED,
            validity=Validity.NOT_MEASURED,
            evaluator_version="x@1",
        )
