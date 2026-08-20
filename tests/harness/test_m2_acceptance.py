"""M2 deterministic replay + baseline acceptance scenarios (EG-M2-5).

End-to-end through the real CLI (`evalglass run` / `evalglass baseline update`): each scenario
demonstrates one honest outcome whose verdict + baseline state are read from the persisted
Scorecard (never recomputed here), and the process exit code matches it. Together they exercise
the M2 surfaces — replay, data policy, baselines, CI exit — and prove replay is deterministic.

- informational: replay fills a non-gating metric → exit 0, no quality claim.
- pass: replay + a **comparable** promoted baseline satisfy a required-baseline gate → exit 0.
- fail: replay yields a wrong output below an approved threshold → exit 1.
- blocked (replay failure): a failed replay cannot make a claim → exit 1.
- blocked (non-comparable baseline): only the dataset dimension changes vs the baseline, so the
  required-baseline gate is non-comparable → exit 1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from evalglass.harness.cli import main
from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config

_ECHO = "import sys,json\nd=json.load(sys.stdin)\nprint(json.dumps({'output': d['input']}))\n"
_WRONG = "import sys,json\njson.load(sys.stdin)\nprint(json.dumps({'output': 'WRONG'}))\n"
_FAIL = "import sys,json\njson.load(sys.stdin)\nsys.exit(2)\n"

_GATE = "\n    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"

_CFG = """
run:
  id: {run_id}
datasets:
  - path: {ds}
    name: {ds}
    status: validated
    data_policy: permitted
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: {ds}{gate}{requires}
task:
  argv: [{py}, {host}]
  timeout_s: 10
{baseline}output:
  dir: reports
"""


def _write_cfg(
    tmp_path: Path,
    *,
    cfg_name: str,
    run_id: str,
    host_body: str,
    gate: bool,
    ds: str = "d.jsonl",
    requires_baseline: bool = False,
    baseline_path: str | None = None,
) -> Path:
    (tmp_path / ds).write_text(
        json.dumps({"input": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )  # output-less → replay fills it
    (tmp_path / "host.py").write_text(host_body, encoding="utf-8")
    baseline_block = (
        f"baseline:\n  path: {baseline_path}\n  comparison_requested: true\n"
        if baseline_path is not None
        else ""
    )
    cfg = tmp_path / f"{cfg_name}.yaml"
    cfg.write_text(
        _CFG.format(
            run_id=run_id,
            ds=ds,
            gate=_GATE if gate else "",
            requires="\n    requires_baseline: true" if requires_baseline else "",
            py=json.dumps(sys.executable),
            host=json.dumps(str(tmp_path / "host.py")),
            baseline=baseline_block,
        ),
        encoding="utf-8",
    )
    return cfg


def _scorecard(tmp_path: Path, run_id: str) -> dict[str, Any]:
    text = (tmp_path / "reports" / run_id / "scorecard.json").read_text()
    return cast("dict[str, Any]", json.loads(text))


def test_informational_replay_no_gate(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, cfg_name="info", run_id="info", host_body=_ECHO, gate=False)
    assert main(["run", "--config", str(cfg)]) == 0
    assert _scorecard(tmp_path, "info")["verdict"]["verdict"] == "informational"


def test_pass_replay_with_comparable_baseline(tmp_path: Path) -> None:
    # First run (same run id, no baseline requirement) → promote it → re-run requiring a
    # comparable baseline. Same gating dimensions → comparable → the gate passes.
    base = _write_cfg(tmp_path, cfg_name="cmpbase", run_id="cmp", host_body=_ECHO, gate=True)
    assert main(["run", "--config", str(base)]) == 0
    rr = tmp_path / "reports" / "cmp" / "runrecord.json"
    bl = tmp_path / "baselines" / "b.json"
    assert main(["baseline", "update", "--from", str(rr), "--to", str(bl)]) == 0

    passing = _write_cfg(
        tmp_path,
        cfg_name="cmppass",
        run_id="cmp",
        host_body=_ECHO,
        gate=True,
        requires_baseline=True,
        baseline_path="baselines/b.json",
    )
    assert main(["run", "--config", str(passing)]) == 0
    sc = _scorecard(tmp_path, "cmp")
    assert sc["verdict"]["verdict"] == "pass"
    assert sc["baseline_state"] == "comparable"


def test_fail_replay_below_threshold(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, cfg_name="fail", run_id="fail", host_body=_WRONG, gate=True)
    assert main(["run", "--config", str(cfg)]) == 1
    assert _scorecard(tmp_path, "fail")["verdict"]["verdict"] == "fail"


def test_blocked_replay_failure(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, cfg_name="blk", run_id="blk", host_body=_FAIL, gate=True)
    assert main(["run", "--config", str(cfg)]) == 1
    assert _scorecard(tmp_path, "blk")["verdict"]["verdict"] == "blocked"


def test_blocked_non_comparable_baseline(tmp_path: Path) -> None:
    # Promote a baseline over dataset d.jsonl, then re-run with the SAME run id (config dimension
    # unchanged) but a DIFFERENT dataset → only the dataset gating dimension changes → the
    # required-baseline gate is non-comparable and blocks. Driven through the real CLI.
    base = _write_cfg(tmp_path, cfg_name="ncbase", run_id="nc", host_body=_ECHO, gate=True)
    assert main(["run", "--config", str(base)]) == 0
    rr = tmp_path / "reports" / "nc" / "runrecord.json"
    bl = tmp_path / "baselines" / "nc.json"
    assert main(["baseline", "update", "--from", str(rr), "--to", str(bl)]) == 0

    regress = _write_cfg(
        tmp_path,
        cfg_name="ncregress",
        run_id="nc",
        host_body=_ECHO,
        gate=True,
        ds="d2.jsonl",
        requires_baseline=True,
        baseline_path="baselines/nc.json",
    )
    assert main(["run", "--config", str(regress)]) == 1
    sc = _scorecard(tmp_path, "nc")
    assert sc["verdict"]["verdict"] == "blocked"
    assert sc["baseline_state"] == "not_comparable"


def test_replay_is_deterministic(tmp_path: Path) -> None:
    # Same input + same host → identical output → identical provenance fingerprint and verdict.
    cfg = _write_cfg(tmp_path, cfg_name="det", run_id="det", host_body=_ECHO, gate=True)
    first = run_config(load_config(str(cfg)), tmp_path)
    second = run_config(load_config(str(cfg)), tmp_path)
    assert first.provenance.dimensions == second.provenance.dimensions
    assert first.scorecard.verdict.verdict == second.scorecard.verdict.verdict
