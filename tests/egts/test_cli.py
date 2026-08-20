"""The `egts` command surface — coverage reporting (EGTS-M0-2).

`egts coverage` reports completeness and names missing obligations. Open
obligations (`partial`) are reported but do not fail plain coverage — missing
proof is *named, not hidden*. (A `not_started` row is an honestly-*deferred*
obligation that carries a mandatory reason; see EG-AT0-6.) An integrity violation
(a row claiming `covered` with no scenario) does fail, and `--require-complete`
fails on any gap (used at milestone acceptance).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.egts.cli import build_parser, main


def _write_registry(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_coverage_reports_open_obligations_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = _write_registry(
        tmp_path / "c.yaml",
        """
        rows:
          - product_ticket: EG-M0-1
            public_contract: TraceEnvelope
            status: partial
            scenario_ids: []
        """,
    )
    code = main(["coverage", "--registry", str(reg)])
    out = capsys.readouterr().out
    assert code == 0
    assert "partial" in out
    assert "TraceEnvelope" in out


def test_coverage_integrity_violation_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = _write_registry(
        tmp_path / "c.yaml",
        """
        rows:
          - product_ticket: EG-M0-1
            public_contract: TraceEnvelope
            status: covered
            scenario_ids: []
        """,
    )
    code = main(["coverage", "--registry", str(reg)])
    assert code != 0
    assert "covered" in capsys.readouterr().out.lower()


def test_coverage_require_complete_fails_on_open_gap(tmp_path: Path) -> None:
    reg = _write_registry(
        tmp_path / "c.yaml",
        """
        rows:
          - product_ticket: EG-M0-1
            public_contract: TraceEnvelope
            status: partial
            scenario_ids: []
        """,
    )
    assert main(["coverage", "--registry", str(reg), "--require-complete"]) != 0


def test_coverage_require_complete_passes_when_all_covered(tmp_path: Path) -> None:
    reg = _write_registry(
        tmp_path / "c.yaml",
        """
        rows:
          - product_ticket: EG-M0-1
            public_contract: TraceEnvelope
            status: covered
            scenario_ids: [m0.contract.trace_envelope.roundtrip]
        """,
    )
    assert main(["coverage", "--registry", str(reg), "--require-complete"]) == 0


def test_unknown_command_errors() -> None:
    with pytest.raises(SystemExit):
        main(["frobnicate"])


def test_evidence_reports_and_passes_when_covered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = _write_registry(
        tmp_path / "c.yaml",
        """
        rows:
          - product_ticket: EG-M0-1
            public_contract: TraceEnvelope
            status: covered
            scenario_ids: [m0.proof.x]
        """,
    )
    code = main(["evidence", "--registry", str(reg), "--target", "EGTS-M0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "EGTS-M0" in out
    assert "m0.proof.x" in out


def test_evidence_fails_with_a_gap(tmp_path: Path) -> None:
    reg = _write_registry(
        tmp_path / "c.yaml",
        """
        rows:
          - product_ticket: EG-M0-1
            public_contract: TraceEnvelope
            status: partial
            scenario_ids: []
        """,
    )
    assert main(["evidence", "--registry", str(reg), "--target", "EGTS-M0"]) != 0


def test_test_core_passes_through_pytest_args() -> None:
    # Dashed pytest flags pass through after `--`; not executed here (would re-run pytest).
    args = build_parser().parse_args(["test-core", "--", "-k", "blocked", "--maxfail=1"])
    assert args.command == "test-core"
    assert args.pytest_args == ["--", "-k", "blocked", "--maxfail=1"]


# --- EGTS-M1 additions (EGTS-M1-6) ------------------------------------------

_EG_M1 = Path(__file__).resolve().parent / "coverage" / "eg_m1.yaml"


def test_test_runtime_command_is_registered() -> None:
    args = build_parser().parse_args(["test-runtime"])
    assert args.command == "test-runtime"


def test_m1_coverage_registry_is_covered(capsys: pytest.CaptureFixture[str]) -> None:
    # The shipped EG-M1 registry has a real scenario for every covered obligation, so it
    # passes coverage with no integrity violations.
    assert main(["coverage", "--registry", str(_EG_M1)]) == 0


def test_m1_coverage_require_complete_passes() -> None:
    assert main(["coverage", "--registry", str(_EG_M1), "--require-complete"]) == 0
