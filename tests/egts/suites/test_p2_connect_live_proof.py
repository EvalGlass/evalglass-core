"""EGTS-P2 — `connect --live` hermetic acceptance proof (EG-P2-4; ADR 0046).

Proves — with **no network and no provider SDK** — that the `connect --live` scaffold produces a
connector lane which the **real** `run_config` then executes: the live SDK call is replaced by an
injected fake `_default_fetch` returning a recorded fixture payload, so the whole seam (resolve →
factory → egress gate → normalize → join the run) is exercised hermetically. A live pull is a trace
source, so authority dilutes to `proposed` and the run stays `informational`. Every negative control
(tests/CLAUDE.md §12) proves the checker family is sensitive: a missing extra is a clean `SKIPPED`;
an approved gating threshold on the pulled (proposed) data cannot pass; and a literal credential is
rejected without echoing the value.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import Verdict
from evalglass.harness import connect
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.lanes import LaneStatus, MissingPrerequisite
from evalglass.harness.runner import run_config
from tests.egts.checkers import check_authority, check_verdict

_FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "adapters"
        / "fixtures"
        / "connectors"
        / "langfuse.json"
    ).read_text(encoding="utf-8")
)


def _metric(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "field_presence",
        "evaluator_ref": "field_presence@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0, 1],
    }
    base.update(over)
    return base


def _config(lane: dict[str, object], metric_over: dict[str, object] | None = None) -> RuntimeConfig:
    return RuntimeConfig.from_mapping(
        {"metrics": [_metric(**(metric_over or {}))], "lanes": [lane]}
    )


def _inject_fetch(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    """Replace the live Langfuse SDK call with a fake that returns ``result`` (or raises it)."""
    from evalglass.adapters import trace_langfuse

    def _fake(self: object) -> Any:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(trace_langfuse.LangfuseTraceSource, "_default_fetch", _fake)


def test_p2_connect_live_scaffold_runs_via_injected_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """p2.connect_live.scaffold_runs — the scaffolded lane pulls via an injected fetch, proposed."""
    _inject_fetch(monkeypatch, _FIXTURE["good"])
    lane = connect.connector_lane_config(
        "langfuse", endpoint="https://lf.example", data_policy="permitted"
    )
    record = run_config(_config(lane), root=tmp_path)
    # Typed artifacts first: the lane RAN and its pulled units became Examples the metric scored.
    statuses = {lr["lane"]: lr["status"] for lr in record.lane_results}
    assert statuses["langfuse-trace"] == LaneStatus.RAN.value
    assert len(record.scores) >= 1
    # A live pull carries no validated gold → proposed authority → informational, never a pass.
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)
    check_authority(record.scorecard, "field_presence", expected_level="informational")


def test_negctl_missing_extra_is_clean_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control (clean-skip): a missing extra ⇒ SKIPPED, the run stays honest."""
    _inject_fetch(monkeypatch, MissingPrerequisite("the langfuse-trace extra is not installed"))
    lane = connect.connector_lane_config(
        "langfuse", endpoint="https://lf.example", data_policy="permitted"
    )
    record = run_config(_config(lane), root=tmp_path)
    statuses = {lr["lane"]: lr["status"] for lr in record.lane_results}
    assert statuses["langfuse-trace"] == LaneStatus.SKIPPED.value  # never a crash
    check_verdict(record.scorecard, expected=Verdict.INFORMATIONAL)


def test_negctl_gate_attempt_on_pulled_proposed_data_never_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control (authority): an approved gate on pulled proposed data cannot pass."""
    _inject_fetch(monkeypatch, _FIXTURE["good"])
    lane = connect.connector_lane_config(
        "langfuse", endpoint="https://lf.example", data_policy="permitted"
    )
    record = run_config(
        _config(
            lane,
            metric_over={
                "metric_status": "gating",
                "threshold_approval": "approved",
                "threshold": 0.1,
                "params": {"required_fields": ["output"]},
            },
        ),
        root=tmp_path,
    )
    # Pulled traces are proposed (no validated gold): the gate cannot fire — never a pass.
    assert record.scorecard.verdict.verdict is not Verdict.PASS


def test_negctl_literal_credential_is_rejected_without_echo() -> None:
    """Negative control (secret safety): a literal credential is rejected and never echoed."""
    # A non-key-shaped literal (hyphens ⇒ not a valid env-var NAME ⇒ rejected); never a real secret.
    literal = "inline-literal-not-an-env-name"
    with pytest.raises(connect.ConnectError) as ei:
        connect.connector_lane_config("langfuse", credentials={"public_key": literal})
    assert literal not in str(ei.value)
