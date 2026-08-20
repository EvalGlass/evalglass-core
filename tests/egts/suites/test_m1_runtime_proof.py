"""EGTS-M1 runtime route proof (EGTS-M1-2 / -3 / -5).

Drives the **real** harness (``load_config`` -> ``run_config``) through dataset-only,
trace-only, mixed, and open-convention routes in fresh isolated workspaces, and checks the
emitted Scorecard against declared expectations. Proves: dataset status reaches Scorecard
authority; the open-convention adapter normalizes spans so no raw/vendor shape reaches an
evaluator (route fidelity); malformed records become diagnostics, not scores; and the
checkers fail closed (negative controls).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core import RunRecord, Verdict
from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config
from tests.egts.checkers import (
    CheckerError,
    check_authority,
    check_route_fidelity,
    check_verdict,
)
from tests.egts.workspace import RuntimeWorkspace, make_workspace

# A host route-fidelity probe: scores 1.0 only when it receives a normalized core Example;
# 0.0 if a raw/vendor trace shape (span attributes/context) leaked into the output.
_CLEAN_PROBE = """
from collections.abc import Mapping

from evalglass.core import Score, ScoreStatus, Validity

_VENDOR_KEYS = {"attributes", "context", "span_id", "resource"}


def _leaked(value):
    return isinstance(value, Mapping) and bool(_VENDOR_KEYS & set(value))


def evaluate(example, context, evidence):
    # Every evaluator-visible surface must be free of raw/vendor trace shape, not just output.
    surfaces = (example.input, example.output, example.context, example.metadata,
                example.provenance)
    leaked = any(_leaked(s) for s in surfaces)
    return Score(metric=context.spec.name, value=0.0 if leaked else 1.0,
                 status=ScoreStatus.SCORED, validity=Validity.VALID, evaluator_version="probe@1")
"""

_EXACT_MATCH = """
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: datasets/d.jsonl
{extra}
"""

_PROBE_METRIC = """
  - name: probe
    evaluator_ref: evaluators/clean_probe.py:evaluate
    lens: non_reference
    score_type: continuous
    score_range: [0, 1]
"""


def _run(ws: RuntimeWorkspace) -> RunRecord:
    return run_config(load_config(ws.config_path), root=ws.root)


def _dataset_ws(
    tmp_path: Path, fixture_id: str, *, status: str, metric_extra: str
) -> RuntimeWorkspace:
    config = (
        "datasets:\n"
        f"  - path: datasets/d.jsonl\n    status: {status}\n    data_policy: permitted\n"
        "metrics:\n" + _EXACT_MATCH.format(extra=metric_extra)
    )
    return make_workspace(
        tmp_path,
        fixture_id,
        config=config,
        datasets={"d.jsonl": json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"},
    )


# --- dataset route + authority (EGTS-M1-2) ----------------------------------


def test_dataset_proposed_stays_informational(tmp_path: Path) -> None:
    gating = "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"
    record = _run(_dataset_ws(tmp_path, "fx1", status="proposed", metric_extra=gating))
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)
    check_authority(record.scorecard, "exact_match", expected_level="informational")


def test_dataset_validated_reaches_gating_authority(tmp_path: Path) -> None:
    gating = "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"
    record = _run(_dataset_ws(tmp_path, "fx2", status="validated", metric_extra=gating))
    check_verdict(record.scorecard, expected=Verdict.PASS)
    check_authority(record.scorecard, "exact_match", expected_level="gating")


def test_forbidden_policy_blocks_and_checker_distinguishes(tmp_path: Path) -> None:
    gating = "    metric_status: gating\n    threshold_approval: approved\n    threshold: 0.5"
    config = (
        "datasets:\n  - path: datasets/d.jsonl\n    status: validated\n"
        "    data_policy: forbidden\nmetrics:\n" + _EXACT_MATCH.format(extra=gating)
    )
    ws = make_workspace(
        tmp_path,
        "fx-blocked",
        config=config,
        datasets={"d.jsonl": json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"},
    )
    record = _run(ws)
    check_verdict(record.scorecard, expected=Verdict.BLOCKED)
    # a blocked gate is level=gating + blocked=True — the checker must require both
    check_authority(record.scorecard, "exact_match", expected_level="gating", expected_blocked=True)
    # negative control: declaring it a clean gate (blocked omitted) must fail
    with pytest.raises(CheckerError):
        check_authority(record.scorecard, "exact_match", expected_level="gating")


# --- trace route + route fidelity (EGTS-M1-3 / -5) --------------------------


def test_open_convention_route_normalizes_no_vendor_leak(tmp_path: Path) -> None:
    span = {
        "context": {"trace_id": "t1"},
        "attributes": {"input.value": "q", "output.value": "a"},
    }
    ws = make_workspace(
        tmp_path,
        "fx3",
        config=(
            "traces:\n  - path: traces/t.jsonl\n    format: openinference\n"
            "    data_policy: permitted\nmetrics:\n" + _PROBE_METRIC
        ),
        traces={"t.jsonl": json.dumps(span) + "\n"},
        evaluators={"clean_probe.py": _CLEAN_PROBE},
    )
    record = _run(ws)
    # the adapter extracted output.value into behavior; the probe saw a normalized Example
    check_route_fidelity(record.scorecard, probe_metric="probe")


def test_route_fidelity_negative_control_detects_leak(tmp_path: Path) -> None:
    # A local trace whose behavior.output is itself a vendor-shaped span mapping → the probe
    # sees the raw shape and scores < 1.0 → the fidelity checker must fail.
    leaked = {"trace_id": "t1", "behavior": {"output": {"attributes": {"x": 1}, "context": {}}}}
    ws = make_workspace(
        tmp_path,
        "fx4",
        config=(
            "traces:\n  - path: traces/t.jsonl\n    format: local\n    data_policy: permitted\n"
            "metrics:\n" + _PROBE_METRIC
        ),
        traces={"t.jsonl": json.dumps(leaked) + "\n"},
        evaluators={"clean_probe.py": _CLEAN_PROBE},
    )
    record = _run(ws)
    with pytest.raises(CheckerError):
        check_route_fidelity(record.scorecard, probe_metric="probe")


# --- mixed route convergence (EGTS-M1-5) ------------------------------------


def test_mixed_route_converges_examples_from_both(tmp_path: Path) -> None:
    ws = make_workspace(
        tmp_path,
        "fx5",
        config=(
            "datasets:\n  - path: datasets/d.jsonl\n"
            "traces:\n  - path: traces/t.jsonl\n    format: local\n"
            "metrics:\n" + _EXACT_MATCH.format(extra="")
        ),
        datasets={"d.jsonl": json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"},
        traces={"t.jsonl": json.dumps({"trace_id": "t1", "behavior": {"output": "x"}}) + "\n"},
    )
    record = _run(ws)
    assert len(record.scores) == 2  # one metric over a dataset example + a trace example


# --- malformed records are evidence, not scores (EGTS-M1-2) -----------------


def test_malformed_record_is_diagnostic_not_score(tmp_path: Path) -> None:
    ws = make_workspace(
        tmp_path,
        "fx6",
        config=(
            "datasets:\n  - path: datasets/d.jsonl\nmetrics:\n" + _EXACT_MATCH.format(extra="")
        ),
        datasets={"d.jsonl": '{"input":"a","output":"1","reference":"1"}\n{ bad json\n'},
    )
    record = _run(ws)
    assert "dataset_invalid_json" in {d.code for d in record.scorecard.diagnostics}
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)  # not a fabricated pass


# --- checker negative control (authority) -----------------------------------


def test_authority_checker_rejects_wrong_declaration(tmp_path: Path) -> None:
    record = _run(_dataset_ws(tmp_path, "fx7", status="proposed", metric_extra=""))
    with pytest.raises(CheckerError):
        check_authority(record.scorecard, "exact_match", expected_level="gating")
