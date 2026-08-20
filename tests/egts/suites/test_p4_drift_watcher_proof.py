"""EGTS-P4 — continuous drift watcher over two runs (EG-P4-4; ADR 0048).

Proves the real harness drift surface (`run_config` → `evaluate_drift`, and the `watch` CLI): a
comparable, interval-clearing regression is flagged; a within-noise delta is not; a not-comparable
pair is guarded (never "no regression"); the exit class is unchanged by drift; and the
baseline file is byte-identical afterwards (the watcher never promotes). Typed drift JSON is
asserted before any printed summary.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core.aggregation import aggregate
from evalglass.core.provenance import REQUIRED_DIMENSIONS, BaselineState, RunFingerprint
from evalglass.core.registry import Aggregation, Direction
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.core.verdict import decide_verdict
from evalglass.harness.cli import main
from evalglass.harness.drift import Comparability, DriftResult, evaluate_drift

_DIR = {"exact_match": Direction.HIGHER_IS_BETTER}


def _score(v: float, eid: str) -> Score:
    return Score("exact_match", v, ScoreStatus.SCORED, Validity.VALID, "1", example_id=eid)


def _record(vals: list[float], state: BaselineState | None, run_id: str) -> RunRecord:
    scores = [_score(v, f"e{i}") for i, v in enumerate(vals)]
    aggs = [aggregate("exact_match", scores, Aggregation.MEAN)]
    sc = Scorecard(verdict=decide_verdict([]), metrics=aggs, authority={}, baseline_state=state)
    dims = {d: {"x": 1} for d in REQUIRED_DIMENSIONS}
    return RunRecord(run_id=run_id, scorecard=sc, scores=scores, provenance=RunFingerprint.of(dims))


def test_p4_comparable_regression_is_flagged() -> None:
    """p4.drift.regression — a comparable, interval-clearing drop is labeled a regression."""
    current = _record([0.0, 0.0, 0.0], BaselineState.COMPARABLE, "cur")
    baseline = _record([1.0, 1.0, 1.0], None, "base")
    result = evaluate_drift(current, baseline, _DIR)
    # Typed drift artifact first.
    d = result.to_dict()
    assert d["comparability"] == "comparable"
    assert d["comparison"]["deltas"]["exact_match"]["outcome"] == "regression"
    assert result.regressions() == ["exact_match"]
    assert DriftResult.from_dict(d) == result


def test_negctl_within_noise_not_flagged() -> None:
    """Negative control: a delta whose paired interval spans zero is within_noise, not flagged."""
    current = _record([1.0, 0.0], BaselineState.COMPARABLE, "cur")
    baseline = _record([0.0, 1.0], None, "base")
    result = evaluate_drift(current, baseline, _DIR)
    assert result.comparability is Comparability.COMPARABLE
    assert result.regressions() == []


def test_negctl_not_comparable_guarded() -> None:
    """Negative control: a not-comparable pair reports not_comparable, never 'no regression'."""
    current = _record([0.0, 0.0], BaselineState.NOT_COMPARABLE, "cur")
    baseline = _record([1.0, 1.0], None, "base")
    result = evaluate_drift(current, baseline, _DIR)
    assert result.comparability is Comparability.NOT_COMPARABLE
    assert result.regressions() == []
    assert result.comparison is None


# --- the real CLI watch surface over run_config: exit unchanged + baseline never promoted --------

_CONFIG = """run:
  id: r1
datasets:
  - path: d.jsonl
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl
{baseline}output:
  dir: reports
"""


def _write(tmp_path: Path, outputs: list[str], baseline: str = "") -> Path:
    rows = [json.dumps({"input": "q", "output": o, "reference": "4"}) for o in outputs]
    (tmp_path / "d.jsonl").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(_CONFIG.format(baseline=baseline), encoding="utf-8")
    return cfg


def test_p4_watch_exit_unchanged_and_baseline_untouched(tmp_path: Path) -> None:
    """p4.drift.no_exit_no_promote — a drift regression changes no exit class and no baseline."""
    # Baseline run over correct outputs → promote.
    cfg = _write(tmp_path, ["4", "4", "4"])
    assert main(["run", "--config", str(cfg)]) == 0
    rr = tmp_path / "reports" / "r1" / "runrecord.json"
    baseline_path = tmp_path / "baselines" / "baseline.json"
    assert main(["baseline", "update", "--from", str(rr), "--to", str(baseline_path)]) == 0
    before = baseline_path.read_bytes()
    # A drifted current run (wrong outputs), same dataset name/version → comparable, and watch it.
    bl = "baseline:\n  path: baselines/baseline.json\n"
    cfg2 = _write(tmp_path, ["x", "x", "x"], baseline=bl)
    rc = main(["watch", "--config", str(cfg2)])
    # Even if a regression is flagged, the informational run exits 0 (drift adds no exit class).
    assert rc == 0
    drift = json.loads((tmp_path / "reports" / "r1" / "drift.json").read_text(encoding="utf-8"))
    assert drift["comparability"] == "comparable"
    # The baseline file is byte-identical — the watcher never promotes.
    assert baseline_path.read_bytes() == before
