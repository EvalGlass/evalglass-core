"""EGTS-M2-4/-5: CI exit/annotation proof + infrastructure-error taxonomy / false-confidence.

Through the real CLI (`evalglass run --format ci`): the exit code and CI annotations derive only
from the product VerdictPayload, and an infrastructure/setup failure is its own class (exit 2),
never a quality verdict. The false-confidence cases prove a good (or bad) score *without gating
authority* stays informational — never a pass or fail — which is the cardinal no-false-confidence
rule. Negative controls seed each checker family with a wrong expectation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import Scorecard, Verdict
from evalglass.harness.cli import main
from tests.egts.checkers import (
    CheckerError,
    check_ci_no_overclaim,
    check_exit_class,
    check_verdict,
)

_GATE = "\n    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"
_CFG = """
run:
  id: {run_id}
datasets:
  - path: d.jsonl
    name: d.jsonl
    status: validated
    data_policy: {policy}
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl{gate}
output:
  dir: reports
"""


def _cfg(
    tmp_path: Path, *, run_id: str, output: str, gate: bool, policy: str = "permitted"
) -> Path:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "4", "output": output, "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = tmp_path / f"{run_id}.yaml"
    cfg.write_text(
        _CFG.format(run_id=run_id, policy=policy, gate=_GATE if gate else ""), encoding="utf-8"
    )
    return cfg


def _scorecard(tmp_path: Path, run_id: str) -> Scorecard:
    return Scorecard.from_dict(
        json.loads((tmp_path / "reports" / run_id / "scorecard.json").read_text())
    )


# --- EGTS-M2-4: CI exit + annotations from the verdict payload ---------------


@pytest.mark.parametrize(
    ("run_id", "output", "gate", "policy", "exit_code", "exit_class"),
    [
        ("info", "4", False, "permitted", 0, "zero"),
        ("pass", "4", True, "permitted", 0, "zero"),
        ("fail", "9", True, "permitted", 1, "nonzero_fail"),
        ("blocked", "4", True, "forbidden", 1, "nonzero_blocked"),
    ],
)
def test_ci_exit_and_annotations_track_verdict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    run_id: str,
    output: str,
    gate: bool,
    policy: str,
    exit_code: int,
    exit_class: str,
) -> None:
    cfg = _cfg(tmp_path, run_id=run_id, output=output, gate=gate, policy=policy)
    assert main(["run", "--config", str(cfg), "--format", "ci"]) == exit_code
    ci_output = capsys.readouterr().out
    scorecard = _scorecard(tmp_path, run_id)
    check_ci_no_overclaim(ci_output, scorecard)
    check_exit_class(scorecard, expected=exit_class)


def test_infrastructure_error_is_distinct_exit_class(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A setup failure before any verdict exits 2 (infrastructure), never the 1 of a quality fail.
    code = main(["run", "--config", str(tmp_path / "nope.yaml"), "--format", "ci"])
    assert code == 2
    assert code != 1  # distinct from the quality-fail class
    assert "setup error" in capsys.readouterr().err


def test_exit_class_checker_rejects_wrong_declaration(tmp_path: Path) -> None:
    # Negative control: a test-only exit class that disagrees with the VerdictPayload must fail.
    cfg = _cfg(tmp_path, run_id="nc1", output="4", gate=False)
    assert main(["run", "--config", str(cfg)]) == 0
    with pytest.raises(CheckerError):
        check_exit_class(_scorecard(tmp_path, "nc1"), expected="nonzero_fail")


def test_ci_overclaim_is_detected(tmp_path: Path) -> None:
    # Negative control: a mutated CI string headlining a stronger verdict must fail the checker.
    cfg = _cfg(tmp_path, run_id="nc2", output="4", gate=False)
    assert main(["run", "--config", str(cfg)]) == 0
    sc = _scorecard(tmp_path, "nc2")  # informational
    # Include the true verdict AND an extra stronger one, so this exercises the overclaim loop
    # (not merely the missing-verdict branch).
    mutated = (
        "::notice title=EvalGlass::verdict=informational ci=exit-zero\n::error::verdict=pass\n"
    )
    with pytest.raises(CheckerError):
        check_ci_no_overclaim(mutated, sc)


# --- EGTS-M2-5: false-confidence refusal -------------------------------------


def test_good_output_without_authority_stays_informational(tmp_path: Path) -> None:
    # A perfect score with no gating authority is NOT a pass — the cardinal false-confidence case.
    cfg = _cfg(tmp_path, run_id="goodinfo", output="4", gate=False)
    assert main(["run", "--config", str(cfg)]) == 0
    check_verdict(_scorecard(tmp_path, "goodinfo"), expected=Verdict.INFORMATIONAL)


def test_bad_output_without_authority_stays_informational(tmp_path: Path) -> None:
    # A failing score with no gating authority is NOT a fail either — still informational.
    cfg = _cfg(tmp_path, run_id="badinfo", output="9", gate=False)
    assert main(["run", "--config", str(cfg)]) == 0
    check_verdict(_scorecard(tmp_path, "badinfo"), expected=Verdict.INFORMATIONAL)
