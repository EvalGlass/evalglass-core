"""EGTS-M3 milestone acceptance gate (M3 Slice 7).

M3 is accepted only when every EG-M3 obligation has a real proof and the milestone evidence
holds no overclaim. This asserts the machine-checkable half: ``egts coverage --require-complete``
passes for the EG-M3 registry (every obligation `covered` with a real scenario), ``egts evidence
--target EGTS-M3`` is clean, and the committed acceptance evidence pack is internally honest —
the first-run report claims only the informational verdict, the scaffolded approval ledger grants
no authority, and the vendored runtime is bounded to the managed root with the skill not vendored.
The validator-gate over that pack returns PASS — run as the documented acceptance step
(docs/IMPLEMENTATION_PLAN.md).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.egts.cli import main

_EGTS = Path(__file__).resolve().parents[1]
_EG_M3 = _EGTS / "coverage" / "eg_m3.yaml"
_PACK = _EGTS / "evidence" / "m3_acceptance.pack.json"


def test_m3_coverage_is_complete() -> None:
    # Every EG-M3 obligation is covered by a real scenario (no open gap, no integrity violation).
    assert main(["coverage", "--registry", str(_EG_M3), "--require-complete"]) == 0


def test_m3_evidence_target_is_clean() -> None:
    assert main(["evidence", "--registry", str(_EG_M3), "--target", "EGTS-M3"]) == 0


def test_m3_acceptance_pack_is_honest() -> None:
    pack = json.loads(_PACK.read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in pack["artifacts"]}
    # The first-run report claims only what the scorecard says (informational; no overclaim).
    assert (
        by_id["m3-rep-firstrun"]["content"]["claimed_status"]
        == (by_id["m3-sc-firstrun"]["content"]["verdict"])
    )
    assert by_id["m3-sc-firstrun"]["content"]["ci_should_fail"] is False
    # Scaffolded assets grant no authority (no silent gate).
    assert by_id["m3-authority"]["content"]["grants_authority"] is False
    # The managed boundary is honest and the skill is not part of the vendored runtime.
    assert by_id["m3-manifest"]["content"]["all_under_managed_root"] is True
    assert by_id["m3-lock"]["content"]["skill_vendored"] is False
