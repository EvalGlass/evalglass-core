"""The `evalglass` CLI entrypoint (EG-M1-1).

The CLI loads config and reports setup diagnostics; it does not own evaluation
meaning. Exit-code contract for M1 slice 1: ``0`` success, ``2`` setup error.
A bad config exits ``2`` with a diagnostic on stderr — never a Python traceback
and never the ``1`` reserved for a quality fail/blocked verdict (build contract §8).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.harness.cli import main

_VALID = """
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "evalglass.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_run_valid_config_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _write(tmp_path, _VALID)
    assert main(["run", "--config", str(cfg)]) == 0


def test_run_missing_config_exits_setup(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "--config", str(tmp_path / "nope.yaml")])
    assert code == 2
    err = capsys.readouterr().err
    assert "config_not_found" in err


def test_run_malformed_config_exits_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _write(tmp_path, "metrics: [unclosed\n")
    code = main(["run", "--config", str(cfg)])
    assert code == 2
    err = capsys.readouterr().err
    assert "config_parse_error" in err
    assert "Traceback" not in err


def test_no_subcommand_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse exits 2 for a usage error (missing required subcommand).
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


# --- end-to-end run (EG-M1-5) ----------------------------------------------


def _dataset(tmp_path: Path, record: dict[str, object]) -> None:
    (tmp_path / "d.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


_RUN_CFG = """
run:
  id: demo
datasets:
  - path: d.jsonl
    status: validated
    data_policy: permitted
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl
{metric_extra}
output:
  dir: reports
"""


def test_run_persists_artifacts_and_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dataset(tmp_path, {"input": "2+2", "output": "4", "reference": "4"})
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=""))
    assert main(["run", "--config", str(cfg)]) == 0
    run_dir = tmp_path / "reports" / "demo"
    assert (run_dir / "runrecord.json").is_file()
    assert (run_dir / "scorecard.json").is_file()
    assert (run_dir / "report.md").is_file()
    out = capsys.readouterr().out
    assert "verdict: informational" in out


def test_run_gating_fail_exits_one(tmp_path: Path) -> None:
    _dataset(tmp_path, {"input": "2+2", "output": "5", "reference": "4"})  # mismatch -> fail
    extra = "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=extra))
    assert main(["run", "--config", str(cfg)]) == 1


def test_run_missing_dataset_file_exits_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # config is valid but the dataset file it references is absent → setup error, exit 2
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=""))
    code = main(["run", "--config", str(cfg)])
    assert code == 2
    assert "dataset_not_found" in capsys.readouterr().err


def test_run_evaluator_contract_violation_exits_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A host evaluator returning an out-of-range score is a setup/infra error, not a quality
    # fail — exit 2, not 1, and no traceback.
    _dataset(tmp_path, {"input": "q", "output": "a", "reference": "a"})
    (tmp_path / "bad.py").write_text(
        "from evalglass.core import Score, ScoreStatus, Validity\n\n\n"
        "def evaluate(example, context, evidence):\n"
        "    return Score(metric=context.spec.name, value=5.0, status=ScoreStatus.SCORED,\n"
        "                 validity=Validity.VALID, evaluator_version='bad@1')\n",
        encoding="utf-8",
    )
    cfg = _write(
        tmp_path,
        """
datasets:
  - path: d.jsonl
metrics:
  - name: bad
    evaluator_ref: bad.py:evaluate
    lens: non_reference
    score_type: continuous
    score_range: [0, 1]
    dataset: d.jsonl
""",
    )
    code = main(["run", "--config", str(cfg)])
    assert code == 2
    assert "evaluator_contract" in capsys.readouterr().err


def test_run_output_path_is_a_file_exits_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --out pointing at an existing file makes persistence fail with an OSError → setup exit 2.
    _dataset(tmp_path, {"input": "2+2", "output": "4", "reference": "4"})
    (tmp_path / "blocker").write_text("not a dir\n", encoding="utf-8")
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=""))
    code = main(["run", "--config", str(cfg), "--out", "blocker"])
    assert code == 2
    assert "io_error" in capsys.readouterr().err


# --- --format ci: CI annotations from the verdict payload (EG-M2-3) ---------


def test_run_format_ci_emits_github_annotations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --format ci renders GitHub workflow commands from the Scorecard; an informational run
    # still exits zero and never headlines a pass.
    _dataset(tmp_path, {"input": "2+2", "output": "4", "reference": "4"})
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=""))
    assert main(["run", "--config", str(cfg), "--format", "ci"]) == 0
    out = capsys.readouterr().out
    assert "::notice" in out
    assert "verdict=informational" in out
    assert "verdict=pass" not in out


def test_run_format_ci_gating_fail_errors_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A failing approved gate exits 1 (from ci_should_fail) and emits an ::error annotation.
    _dataset(tmp_path, {"input": "2+2", "output": "5", "reference": "4"})
    extra = "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=extra))
    assert main(["run", "--config", str(cfg), "--format", "ci"]) == 1
    assert "::error" in capsys.readouterr().out


def test_run_default_format_is_terminal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Without --format, the terminal summary renders (not CI workflow commands).
    _dataset(tmp_path, {"input": "2+2", "output": "4", "reference": "4"})
    cfg = _write(tmp_path, _RUN_CFG.format(metric_extra=""))
    assert main(["run", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "verdict: informational" in out
    assert "::notice" not in out


def test_invalid_format_is_usage_error(tmp_path: Path) -> None:
    cfg = _write(tmp_path, _VALID)
    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(cfg), "--format", "bogus"])
    assert exc.value.code == 2
