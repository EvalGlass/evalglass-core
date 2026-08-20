"""EGTS-M4 milestone acceptance gate (M4 Slice 7).

M4 is accepted only when every EG-M4 obligation has a real proof and the milestone evidence
holds no overclaim. This asserts the machine-checkable half: ``egts coverage --require-complete``
passes for the EG-M4 registry (every obligation `covered` with a real scenario) and ``egts
evidence --target EGTS-M4`` is clean. The validator-gate over the M4 pack is the documented
acceptance step (docs/IMPLEMENTATION_PLAN.md), run alongside this.
"""

from __future__ import annotations

from pathlib import Path

from tests.egts.cli import main

_EG_M4 = Path(__file__).resolve().parents[1] / "coverage" / "eg_m4.yaml"


def test_m4_coverage_is_complete() -> None:
    # Every EG-M4 obligation is covered by a real scenario (no open gap, no integrity violation).
    assert main(["coverage", "--registry", str(_EG_M4), "--require-complete"]) == 0


def test_m4_evidence_target_is_clean() -> None:
    assert main(["evidence", "--registry", str(_EG_M4), "--target", "EGTS-M4"]) == 0
