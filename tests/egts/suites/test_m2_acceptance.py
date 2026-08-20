"""EGTS-M2 milestone acceptance gate (M2 Slice 11).

M2 is accepted only when every EG-M2 obligation has a real proof and the milestone evidence
holds no overclaim. This asserts the machine-checkable half: ``egts coverage --require-complete``
passes for the EG-M2 registry (every obligation `covered` with a real scenario), ``egts evidence
--target EGTS-M2`` is clean, and the committed acceptance evidence pack is internally honest
(each report's claimed status equals its product verdict; the informational run does not fail CI).
The validator-gate over that pack returns PASS — run as the documented acceptance step
(docs/IMPLEMENTATION_PLAN.md).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.egts.cli import main

_EGTS = Path(__file__).resolve().parents[1]
_EG_M2 = _EGTS / "coverage" / "eg_m2.yaml"
_PACK = _EGTS / "evidence" / "m2_acceptance.pack.json"


def test_m2_coverage_is_complete() -> None:
    # Every EG-M2 obligation is covered by a real scenario (no open gap, no integrity violation).
    assert main(["coverage", "--registry", str(_EG_M2), "--require-complete"]) == 0


def test_m2_evidence_target_is_clean() -> None:
    assert main(["evidence", "--registry", str(_EG_M2), "--target", "EGTS-M2"]) == 0


def test_m2_acceptance_pack_is_honest() -> None:
    pack = json.loads(_PACK.read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in pack["artifacts"]}
    # Each public report's claimed status equals its product scorecard verdict (no overclaim).
    for sc_id, rep_id in (("m2-sc-blocked", "m2-rep-blocked"), ("m2-sc-info", "m2-rep-info")):
        assert by_id[rep_id]["content"]["claimed_status"] == by_id[sc_id]["content"]["verdict"]
    # The informational run does not fail CI; the blocked run does.
    assert by_id["m2-sc-info"]["content"]["ci_should_fail"] is False
    assert by_id["m2-sc-blocked"]["content"]["ci_should_fail"] is True
    # The passing required-baseline run is backed by a comparable baseline (regression honesty).
    assert by_id["m2-sc-comparable"]["content"]["verdict"] == "pass"
    assert by_id["m2-baseline"]["content"]["state"] == "comparable"
