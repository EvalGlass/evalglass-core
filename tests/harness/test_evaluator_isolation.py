"""Host-evaluator exception isolation (EG-NR-5).

An arbitrary exception raised inside a host evaluator body is an **infrastructure/setup** failure,
not a host-quality result. It must become a typed diagnostic + exit ``2`` (never a fabricated low
score, never an uncaught traceback + exit ``1`` that reads like a quality fail). A score-*contract*
violation stays its own distinct code (``evaluator_contract``); a valid evaluator still scores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.harness.cli import main

_DATASET = json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"

_CONFIG = """
run:
  id: iso
datasets:
  - path: d.jsonl
metrics:
  - name: m
    evaluator_ref: evaluators/{module}.py:evaluate
    lens: non_reference
    score_type: binary
output:
  dir: reports
"""


def _host(tmp_path: Path, module: str, body: str) -> Path:
    (tmp_path / "d.jsonl").write_text(_DATASET, encoding="utf-8")
    (tmp_path / "evaluators").mkdir(exist_ok=True)
    (tmp_path / "evaluators" / f"{module}.py").write_text(body, encoding="utf-8")
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(_CONFIG.format(module=module), encoding="utf-8")
    return cfg


_CRASH = """
def evaluate(example, context, evidence):
    raise KeyError("boom-" + str({}["missing"]))
"""

_VALID = """
from evalglass.core import Score, ScoreStatus, Validity

def evaluate(example, context, evidence):
    return Score(metric=context.spec.name, value=1.0, status=ScoreStatus.SCORED,
                 validity=Validity.VALID, evaluator_version="host@1")
"""


def test_host_evaluator_crash_is_infrastructure_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _host(tmp_path, "crash", _CRASH)
    code = main(["run", "--config", str(cfg)])
    assert code == 2  # infrastructure/setup, NOT 1 (quality) and NOT an uncaught traceback
    err = capsys.readouterr().err
    assert "evaluator_crashed" in err
    assert "KeyError" in err  # the cause type is named
    # No fabricated score/verdict artifacts imply a quality result.
    assert not (tmp_path / "reports" / "iso" / "scorecard.json").exists()


_BAD_RETURN = """
def evaluate(example, context, evidence):
    return {"value": 1.0}  # a bare mapping, not a Score/ScoreBatch
"""


def test_host_evaluator_bad_return_is_infrastructure_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # An invalid return type must be a typed setup error (exit 2), not a TypeError raised deep in
    # the core (replace() on a non-dataclass) that escapes as an uncaught exit-1 traceback.
    cfg = _host(tmp_path, "badret", _BAD_RETURN)
    code = main(["run", "--config", str(cfg)])
    assert code == 2
    err = capsys.readouterr().err
    assert "evaluator_bad_return" in err
    assert "dict" in err  # names the offending return type


def test_valid_host_evaluator_still_scores(tmp_path: Path) -> None:
    cfg = _host(tmp_path, "ok", _VALID)
    assert main(["run", "--config", str(cfg)]) == 0  # specificity: the guard doesn't over-trigger


def test_evaluator_import_failure_is_infrastructure_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "d.jsonl").write_text(_DATASET, encoding="utf-8")
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(_CONFIG.format(module="does_not_exist"), encoding="utf-8")
    assert main(["run", "--config", str(cfg)]) == 2  # a distinct load-time code, still infra


def test_debug_surfaces_the_original_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _host(tmp_path, "crash", _CRASH)
    assert main(["run", "--config", str(cfg), "--debug"]) == 2
    err = capsys.readouterr().err
    assert "Traceback" in err  # under --debug the original crash traceback is shown
