"""EGTS-M1 milestone acceptance gate (M1 Slice 11).

M1 is accepted only when every product obligation has a real proof and the milestone evidence
holds no overclaim. This asserts the machine-checkable half: ``egts coverage --require-complete``
passes for the EG-M1 registry (every obligation `covered` with a real scenario), ``egts
evidence --target EGTS-M1`` is clean, and the committed acceptance evidence pack is internally
honest (the report's claimed status equals the product verdict). The validator-gate over that
pack returns PASS — run as the documented acceptance step (see docs/IMPLEMENTATION_PLAN.md).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.egts.cli import main

_EGTS = Path(__file__).resolve().parents[1]
_EG_M1 = _EGTS / "coverage" / "eg_m1.yaml"
_PACK = _EGTS / "evidence" / "m1_acceptance.pack.json"


def test_m1_coverage_is_complete() -> None:
    # Every EG-M1 obligation is covered by a real scenario (no open gap, no integrity violation).
    assert main(["coverage", "--registry", str(_EG_M1), "--require-complete"]) == 0


def test_m1_evidence_target_is_clean() -> None:
    assert main(["evidence", "--registry", str(_EG_M1), "--target", "EGTS-M1"]) == 0


def test_m1_acceptance_pack_is_honest() -> None:
    pack = json.loads(_PACK.read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in pack["artifacts"]}
    scorecard = by_id["m1-scorecard"]["content"]
    report = by_id["m1-report"]["content"]
    # the report does not overclaim: its claimed status equals the product verdict
    assert report["claimed_status"] == scorecard["verdict"]
    # an informational run does not fail CI
    assert scorecard["verdict"] == "informational"
    assert scorecard["ci_should_fail"] is False
