"""Scoped hermetic acceptance — the validator-gate is ACTUALLY invoked (EG-H5-4; closes audit W4).

The earlier acceptance suite proved the m5c pack is real-run-derived and symmetric, but it never ran
the pack through the gate. This suite runs the **real validator-gate binary** end-to-end: it must
PASS the honest, committed m5c acceptance pack (now including connector lane-result evidence) and
FAIL overclaiming variants (an external verdict overclaim + two connector-specific overclaims). It
also pins the post-live-connector coverage shape — seven covered rows (EG-M5C-1/2/3/4/5/6/8) and
one honestly-deferred row, EG-M5C-7 per-source-function (the ADR-backed never-build).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.egts.coverage_registry import CoverageStatus, load_registry
from tests.egts.m5c_pack import (
    connector_authority_overclaim_variant,
    connector_sdk_required_variant,
    overclaiming_variant,
)

_REPO = Path(__file__).resolve().parents[3]
_VALIDATOR = _REPO / ".claude" / "skills" / "validator-gate" / "scripts" / "validator.py"
_PACK = _REPO / "tests" / "egts" / "evidence" / "m5c_acceptance.pack.json"
_COVERAGE = _REPO / "tests" / "egts" / "coverage" / "eg_m5c.yaml"

_EXIT_PASS = 0
_EXIT_FAIL = 1


def _run_validator(pack_path: Path) -> int:
    """Invoke the real validator-gate ``run`` over a pack; return its exit code (0=PASS, 1=FAIL)."""
    completed = subprocess.run(  # noqa: S603 - trusted interpreter + a fixed in-repo script path
        [sys.executable, str(_VALIDATOR), "run", "--evidence-pack", str(pack_path)],
        capture_output=True,
        text=True,
        cwd=_REPO,
        check=False,
    )
    return completed.returncode


def test_validator_gate_passes_the_honest_m5c_pack() -> None:
    """The committed, real-run-derived m5c acceptance pack PASSES the gate (exit 0)."""
    assert _run_validator(_PACK) == _EXIT_PASS


def test_validator_gate_fails_an_overclaiming_pack(tmp_path: Path) -> None:
    """Negative control (end-to-end): an overclaiming variant — an external surface claiming pass
    over an informational run — FAILS the gate (exit 1), so the acceptance gate has teeth."""
    variant = overclaiming_variant(json.loads(_PACK.read_text(encoding="utf-8")))
    overclaim = tmp_path / "overclaim.pack.json"
    overclaim.write_text(json.dumps(variant), encoding="utf-8")
    assert _run_validator(overclaim) == _EXIT_FAIL


def _write(tmp_path: Path, name: str, pack: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(pack), encoding="utf-8")
    return path


def test_validator_gate_fails_a_connector_treated_as_required(tmp_path: Path) -> None:
    """Connector negative control (EG-R4-4): marking the opt-in connector lane treated_as_required
    — an optional provider SDK presented as a REQUIRED EvalGlass dependency — FAILS the gate
    (integration_boundary), so 'the SDK is required' can never pass."""
    variant = connector_sdk_required_variant(json.loads(_PACK.read_text(encoding="utf-8")))
    assert _run_validator(_write(tmp_path, "sdk_required.pack.json", variant)) == _EXIT_FAIL


def test_validator_gate_fails_a_connector_authority_overclaim(tmp_path: Path) -> None:
    """Connector negative control (EG-R4-4): an external surface claiming the run passed *because a
    connector pull succeeded*, over an informational run, FAILS the gate (authority_verdict) — a
    connector imports evidence, never authority."""
    variant = connector_authority_overclaim_variant(json.loads(_PACK.read_text(encoding="utf-8")))
    assert _run_validator(_write(tmp_path, "connector_authority.pack.json", variant)) == _EXIT_FAIL


def test_acceptance_is_seven_covered_one_deferred() -> None:
    """After the live-connector tranche (EG-R4 flipped EG-M5C-6, proven by the connector evidence in
    this very pack): EG-M5C-1/2/3/4/5/6/8 covered; only EG-M5C-7 (per-source-function) honestly
    deferred as the ADR-backed never-build."""
    registry = load_registry(_COVERAGE)
    covered = {r.product_ticket for r in registry.rows if r.status is CoverageStatus.COVERED}
    deferred = {r.product_ticket for r in registry.rows if r.status is CoverageStatus.NOT_STARTED}
    assert covered == {f"EG-M5C-{n}" for n in (1, 2, 3, 4, 5, 6, 8)}
    assert deferred == {"EG-M5C-7"}
