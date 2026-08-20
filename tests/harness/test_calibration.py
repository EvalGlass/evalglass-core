"""Host-owned calibration + threshold approval (EG-M4-3).

A judge metric can gate **only** with host-owned, complete approval records under
``evals/calibration/*.json``: a ``CalibrationRecord`` (the judge is calibrated, with an
approver, a rationale, and variance evidence over multiple runs) and an ``ApprovedThreshold``
(value + direction + variance + approver + rationale + version). The harness *derives* the
``JudgeCalibration`` enum + threshold approval from these records and feeds the existing
``resolve_authority``; it **never invents an approver**. A missing field makes the record
incomplete → a setup error, never a silent gate (P8/P15). No record ⇒ ``UNCALIBRATED``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import (
    AuthorityLevel,
    ContractError,
    Direction,
    JudgeCalibration,
    ThresholdApproval,
    Verdict,
)
from evalglass.harness.calibration import (
    ApprovedThreshold,
    CalibrationFile,
    derive_calibration,
    load_calibration,
)
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.runner import run_config

_CAL = {
    "status": "calibrated",
    "approver": "alice",
    "rationale": "50 human labels",
    "variance_runs": 5,
}
_THRESH = {
    "value": 0.5,
    "direction": "higher_is_better",
    "variance": 0.05,
    "approver": "alice",
    "rationale": "p95 of baseline",
    "version": "1",
}


def _file(**over: Any) -> CalibrationFile:
    data: dict[str, Any] = {"calibration": dict(_CAL), "threshold": dict(_THRESH), **over}
    return CalibrationFile.from_mapping(data)


# --- contract parsing: schema-open, fail-closed -----------------------------


def test_parses_a_complete_file() -> None:
    f = _file()
    assert f.calibration.status is JudgeCalibration.CALIBRATED
    assert f.threshold is not None
    assert f.threshold.approver == "alice"


@pytest.mark.parametrize(
    "missing", ["value", "direction", "variance", "approver", "rationale", "version"]
)
def test_incomplete_approved_threshold_is_rejected(missing: str) -> None:
    bad = dict(_THRESH)
    del bad[missing]
    with pytest.raises(ContractError):
        ApprovedThreshold.from_mapping(bad, "threshold")


@pytest.mark.parametrize("missing", ["status", "approver", "rationale", "variance_runs"])
def test_incomplete_calibration_record_is_rejected(missing: str) -> None:
    bad = dict(_CAL)
    del bad[missing]
    with pytest.raises(ContractError):
        _file(calibration=bad)


def test_calibrated_without_variance_evidence_is_rejected() -> None:
    # claiming "calibrated" with too few variance runs is not real calibration evidence
    with pytest.raises(ContractError):
        _file(calibration={**_CAL, "variance_runs": 1})


def test_unknown_calibration_status_is_rejected() -> None:
    with pytest.raises(ContractError):
        _file(calibration={**_CAL, "status": "vibes"})


# --- derive: complete records confer authority; nothing fabricated ----------


def test_calibrated_with_approved_threshold_can_gate() -> None:
    outcome = derive_calibration(_file(), (0.0, 1.0), Direction.HIGHER_IS_BETTER)
    assert outcome.judge_calibration is JudgeCalibration.CALIBRATED
    assert outcome.threshold_approval is ThresholdApproval.APPROVED
    assert outcome.threshold == pytest.approx(0.5)


def test_calibrated_without_threshold_stays_proposed() -> None:
    outcome = derive_calibration(_file(threshold=None), (0.0, 1.0), Direction.HIGHER_IS_BETTER)
    assert outcome.judge_calibration is JudgeCalibration.CALIBRATED
    assert outcome.threshold_approval is ThresholdApproval.PROPOSED
    assert outcome.threshold is None


def test_drifted_calibration_is_carried_through() -> None:
    outcome = derive_calibration(
        _file(calibration={**_CAL, "status": "drifted"}), (0.0, 1.0), Direction.HIGHER_IS_BETTER
    )
    assert outcome.judge_calibration is JudgeCalibration.DRIFTED


def test_threshold_outside_score_range_is_rejected() -> None:
    with pytest.raises(ContractError):
        derive_calibration(
            _file(threshold={**_THRESH, "value": 2.0}), (0.0, 1.0), Direction.HIGHER_IS_BETTER
        )


def test_direction_mismatch_is_rejected() -> None:
    mismatched = _file(threshold={**_THRESH, "direction": "lower_is_better"})
    with pytest.raises(ContractError):
        derive_calibration(mismatched, (0.0, 1.0), Direction.HIGHER_IS_BETTER)


def test_negative_variance_is_rejected() -> None:
    with pytest.raises(ContractError):
        ApprovedThreshold.from_mapping({**_THRESH, "variance": -1.0}, "threshold")


# --- loading: host-owned, fail-closed ---------------------------------------


def test_load_missing_calibration_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SetupError):
        load_calibration("calibration/nope.json", tmp_path)


def test_load_managed_path_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SetupError):
        load_calibration("_evalglass/c.json", tmp_path)


# --- run_config: the whole gate, end to end ---------------------------------


# A real MEASUREMENT judge, run hermetically as a host subprocess (the command adapter). Its
# capability — not a config name — is what lets a calibrated judge gate (EG-NR-1).
_MEASUREMENT_JUDGE = """\
import sys, json
d = json.load(sys.stdin)
print(json.dumps({"value": 1.0, "rationale": "ok"}))
"""


def _write(
    tmp_path: Path, calibration: dict[str, Any] | None, *, adapter: str = "command"
) -> RuntimeConfig:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a", "reference": "a"}) + "\n",
        encoding="utf-8",
    )
    metric: dict[str, Any] = {
        "name": "exact_match",
        "evaluator_ref": "exact_match@1",
        "lens": "reference",
        "score_type": "binary",
        "required_evidence": ["judge"],
        "metric_status": "gating",
    }
    if calibration is not None:
        (tmp_path / "calibration").mkdir(exist_ok=True)
        (tmp_path / "calibration" / "exact_match.json").write_text(
            json.dumps(calibration), encoding="utf-8"
        )
        metric["calibration"] = "calibration/exact_match.json"
    if adapter == "command":
        (tmp_path / "judges").mkdir(exist_ok=True)
        (tmp_path / "judges" / "j.py").write_text(_MEASUREMENT_JUDGE, encoding="utf-8")
        judge: dict[str, Any] = {"adapter": "command", "command": [sys.executable, "judges/j.py"]}
    else:
        judge = {"adapter": "fake", "default_value": 1.0}
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": judge,
        "metrics": [metric],
    }
    return RuntimeConfig.from_mapping(raw)


def test_calibrated_approved_measurement_judge_gates_and_passes(tmp_path: Path) -> None:
    # Positive path (EG-NR-1): a REAL measurement judge, calibrated + approved, gates and passes.
    record = run_config(_write(tmp_path, {"calibration": _CAL, "threshold": _THRESH}), tmp_path)
    assert record.scorecard.authority["exact_match"].can_gate
    assert record.scorecard.verdict.verdict is Verdict.PASS  # score 1.0 >= approved 0.5


def test_fake_judge_cannot_gate_even_when_calibrated(tmp_path: Path) -> None:
    # The negative control (EG-NR-1): a synthetic (fake) judge stays informational even with a
    # complete calibration record + approved threshold — capability precedes calibration.
    record = run_config(
        _write(tmp_path, {"calibration": _CAL, "threshold": _THRESH}, adapter="fake"), tmp_path
    )
    auth = record.scorecard.authority["exact_match"]
    assert auth.level is AuthorityLevel.INFORMATIONAL
    assert not auth.can_gate
    assert "judge_fake_non_authoritative" in auth.reasons
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL


def test_drifted_judge_metric_blocks(tmp_path: Path) -> None:
    record = run_config(
        _write(tmp_path, {"calibration": {**_CAL, "status": "drifted"}, "threshold": _THRESH}),
        tmp_path,
    )
    auth = record.scorecard.authority["exact_match"]
    assert auth.level is AuthorityLevel.GATING  # drifted is an active gate...
    assert not auth.can_gate  # ...that is blocked, not gating
    assert record.scorecard.verdict.verdict is Verdict.BLOCKED


def test_incomplete_threshold_is_a_setup_error(tmp_path: Path) -> None:
    bad_threshold = {"value": 0.5, "direction": "higher_is_better"}  # missing approver/variance/…
    with pytest.raises(SetupError):
        run_config(_write(tmp_path, {"calibration": _CAL, "threshold": bad_threshold}), tmp_path)


def test_no_calibration_file_stays_uncalibrated(tmp_path: Path) -> None:
    record = run_config(_write(tmp_path, None), tmp_path)
    assert record.scorecard.authority["exact_match"].level is AuthorityLevel.INFORMATIONAL


def test_yaml_cannot_self_declare_calibration_without_a_record(tmp_path: Path) -> None:
    # a judge metric cannot gate by setting judge_calibration/threshold_approval in the yaml;
    # only a host-owned calibration FILE can confer gating authority (P1 fix).
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": "e1", "input": "q", "output": "a", "reference": "a"}) + "\n",
        encoding="utf-8",
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": {"adapter": "fake", "default_value": 1.0},
        "metrics": [
            {
                "name": "exact_match",
                "evaluator_ref": "exact_match@1",
                "lens": "reference",
                "score_type": "binary",
                "required_evidence": ["judge"],
                "judge_calibration": "calibrated",
                "threshold_approval": "approved",
                "threshold": 0.5,
                "metric_status": "gating",
            }
        ],
    }
    record = run_config(RuntimeConfig.from_mapping(raw), tmp_path)
    assert record.scorecard.authority["exact_match"].level is AuthorityLevel.INFORMATIONAL


def test_applied_calibration_enters_provenance(tmp_path: Path) -> None:
    a = run_config(
        _write(tmp_path, {"calibration": _CAL, "threshold": {**_THRESH, "value": 0.5}}), tmp_path
    ).provenance
    b = run_config(
        _write(tmp_path, {"calibration": _CAL, "threshold": {**_THRESH, "value": 0.6}}), tmp_path
    ).provenance
    assert a != b  # the applied, file-derived threshold is recorded in the run provenance
