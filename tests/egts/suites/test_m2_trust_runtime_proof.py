"""EGTS-M2-1: subprocess TaskRunner route proof + infrastructure-failure separation.

Drives the **real** harness (``load_config`` -> ``run_config``) through the replay route with
deterministic specimen programs in fresh isolated workspaces. Proves: a good replay fills the
missing output and the gate scores; every host failure mode (missing/malformed output, timeout,
non-zero exit) becomes typed *infrastructure* evidence and **blocks** an active gate — never a
``0.0`` quality score; and the replay genuinely uses the subprocess (route fidelity). The
negative control supplies output in-process (no replay) and the route checker fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evalglass.core import RunRecord, ScoreStatus, Verdict
from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config
from tests.egts.checkers import CheckerError, check_replay_via_subprocess, check_verdict
from tests.egts.workspace import RuntimeWorkspace, make_workspace

# Every specimen first records that it ran (the route-fidelity ledger marker), then behaves.
_MARK = "import pathlib; pathlib.Path('CALLED').write_text('1')\n"
_GOOD = _MARK + "import sys, json\nprint(json.dumps({'output': json.load(sys.stdin)['input']}))\n"
_MISSING = _MARK + "import sys, json\njson.load(sys.stdin)\nprint(json.dumps({'nope': 1}))\n"
_MALFORMED = _MARK + "import sys, json\njson.load(sys.stdin)\nprint('not json')\n"
_TIMEOUT = _MARK + "import sys, json, time\njson.load(sys.stdin)\ntime.sleep(5)\n"
_EXIT = _MARK + "import sys, json\njson.load(sys.stdin)\nsys.exit(2)\n"

_GATE = "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5\n"


def _ws(
    tmp_path: Path, fixture_id: str, specimen: str, *, timeout: int = 10, with_output: bool = False
) -> RuntimeWorkspace:
    record: dict[str, object] = {"input": "4", "reference": "4"}
    if with_output:
        record["output"] = "4"  # present output → no replay (the in-process bypass)
    config = (
        "datasets:\n  - path: datasets/d.jsonl\n    status: validated\n    data_policy: permitted\n"
        f"task:\n  argv: [{json.dumps(sys.executable)}, specimen.py]\n  timeout_s: {timeout}\n"
        "metrics:\n  - name: exact_match\n    evaluator_ref: exact_match@1\n    lens: reference\n"
        "    score_type: binary\n    dataset: datasets/d.jsonl\n" + _GATE
    )
    ws = make_workspace(
        tmp_path, fixture_id, config=config, datasets={"d.jsonl": json.dumps(record) + "\n"}
    )
    (ws.root / "specimen.py").write_text(specimen, encoding="utf-8")
    return ws


def _run(ws: RuntimeWorkspace) -> RunRecord:
    return run_config(load_config(str(ws.config_path)), root=ws.root)


def test_good_replay_scores_and_uses_subprocess(tmp_path: Path) -> None:
    ws = _ws(tmp_path, "m2-good", _GOOD)
    record = _run(ws)
    check_verdict(record.scorecard, expected=Verdict.PASS)
    check_replay_via_subprocess(ws.root)  # the host subprocess really ran


@pytest.mark.parametrize(
    ("fixture_id", "specimen", "code"),
    [
        ("m2-missing", _MISSING, "task_missing_output"),
        ("m2-malformed", _MALFORMED, "task_malformed_output"),
        ("m2-exit", _EXIT, "task_nonzero_exit"),
    ],
)
def test_host_failure_blocks_never_scores(
    tmp_path: Path, fixture_id: str, specimen: str, code: str
) -> None:
    record = _run(_ws(tmp_path, fixture_id, specimen))
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)
    assert code in {d.code for d in record.scorecard.diagnostics}
    # The infrastructure failure is never a fabricated quality score.
    assert all(s.status is not ScoreStatus.SCORED for s in record.scores)


def test_timeout_blocks(tmp_path: Path) -> None:
    record = _run(_ws(tmp_path, "m2-timeout", _TIMEOUT, timeout=1))
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)
    assert "task_timeout" in {d.code for d in record.scorecard.diagnostics}
    # Same invariant as the other failure modes: a timeout is never a fabricated quality score.
    assert all(s.status is not ScoreStatus.SCORED for s in record.scores)


def test_route_fidelity_negative_control(tmp_path: Path) -> None:
    # Output supplied in the dataset → no replay → the subprocess is never invoked → the
    # route-fidelity checker must fail (it caught the bypass).
    ws = _ws(tmp_path, "m2-inproc", _GOOD, with_output=True)
    _run(ws)
    with pytest.raises(CheckerError):
        check_replay_via_subprocess(ws.root)
