"""Per-source coverage manifests through the adapters + a run (Epic B, B2).

Every source read (dataset, local trace, connector lane — including a blocked/skipped one) yields
exactly one manifest; a partial or empty import is typed as such and never looks complete; the
manifests are evidence only (off the Scorecard) and are persisted + round-trip on the RunRecord.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.adapters.dataset_jsonl import LocalJsonlDatasetStore
from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
from evalglass.core import DatasetStatus, RunRecord, Verdict
from evalglass.harness.config import DatasetConfig, RuntimeConfig, TraceConfig
from evalglass.harness.connect import connector_lane_config
from evalglass.harness.coverage import SourceCompleteness
from evalglass.harness.runner import run_config


def _metric() -> dict[str, object]:
    return {
        "name": "structural_shape",
        "evaluator_ref": "structural_shape@1",
        "lens": "non_reference",
        "score_type": "binary",
    }


# --------------------------------------------------------------------------- #
# Adapter-level manifests
# --------------------------------------------------------------------------- #


def test_dataset_manifest_complete(tmp_path: Path) -> None:
    ds = tmp_path / "d.jsonl"
    ds.write_text(
        json.dumps({"input": "a", "output": "b", "reference": "b"})
        + "\n"
        + json.dumps({"input": "c", "output": "d"})
        + "\n",
        encoding="utf-8",
    )
    read = LocalJsonlDatasetStore(
        DatasetConfig(path="d.jsonl", name="d", status=DatasetStatus.PROPOSED), tmp_path
    ).read()
    m = read.manifest
    assert m is not None
    assert m.kind == "dataset"
    assert m.completeness is SourceCompleteness.COMPLETE
    assert (m.records_seen, m.units_emitted, m.rejected) == (2, 2, 0)
    assert m.availability["reference"] is True  # one row had a reference


def test_trace_manifest_partial_on_malformed_line(tmp_path: Path) -> None:
    tr = tmp_path / "t.jsonl"
    tr.write_text(
        json.dumps({"trace_id": "t1", "behavior": {"input": "i", "output": "o"}})
        + "\n"
        + "{ this is not json\n",
        encoding="utf-8",
    )
    read = LocalJsonlTraceSource(TraceConfig(path="t.jsonl", name="t"), tmp_path).read()
    m = read.manifest
    assert m is not None
    assert m.completeness is SourceCompleteness.PARTIAL  # a rejected record → partial
    assert m.records_seen == 2
    assert m.units_emitted == 1
    assert m.rejected == 1
    # Every rejected record contributes a diagnostic (B2 AC #3).
    assert len(m.diagnostics) == m.rejected


def test_trace_manifest_empty_on_empty_file(tmp_path: Path) -> None:
    tr = tmp_path / "empty.jsonl"
    tr.write_text("", encoding="utf-8")
    read = LocalJsonlTraceSource(TraceConfig(path="empty.jsonl", name="e"), tmp_path).read()
    assert read.manifest is not None
    assert read.manifest.completeness is SourceCompleteness.EMPTY  # not complete (B2 AC #2)


# --------------------------------------------------------------------------- #
# Run-level: one manifest per source, evidence-only, round-trips on RunRecord
# --------------------------------------------------------------------------- #


def _run(tmp_path: Path, extra: dict[str, object]) -> RunRecord:
    ds = tmp_path / "d.jsonl"
    ds.write_text(json.dumps({"input": "a", "output": {"x": 1}}) + "\n", encoding="utf-8")
    tr = tmp_path / "t.jsonl"
    tr.write_text(
        json.dumps({"trace_id": "t1", "behavior": {"input": "i", "output": {"y": 2}}}) + "\n",
        encoding="utf-8",
    )
    cfg = {
        "run": {"id": "r"},
        "datasets": [{"path": "d.jsonl"}],
        "traces": [{"path": "t.jsonl", "format": "local"}],
        "metrics": [_metric()],
        **extra,
    }
    return run_config(RuntimeConfig.from_mapping(cfg), tmp_path)


def test_run_emits_one_manifest_per_source(tmp_path: Path) -> None:
    record = _run(tmp_path, {})
    manifests = record.source_manifests
    assert len(manifests) == 2  # one dataset + one trace
    kinds = {m["kind"] for m in manifests}
    assert kinds == {"dataset", "trace"}


def test_manifests_are_evidence_not_authority(tmp_path: Path) -> None:
    record = _run(tmp_path, {})
    # Manifests live on the RunRecord, never on the verdict-bearing Scorecard.
    assert "source_manifests" not in record.scorecard.to_dict()
    assert record.scorecard.verdict.verdict is Verdict.INFORMATIONAL


def test_runrecord_round_trips_manifests(tmp_path: Path) -> None:
    record = _run(tmp_path, {})
    back = RunRecord.from_dict(record.to_dict())
    assert back.source_manifests == record.source_manifests


def test_blocked_lane_still_records_a_manifest(tmp_path: Path) -> None:
    # An enabled connector lane with the default 'unknown' policy refuses egress → BLOCKED manifest.
    lane = connector_lane_config("langfuse", endpoint="https://lf.example")
    record = _run(tmp_path, {"lanes": [lane]})
    lane_manifests = [m for m in record.source_manifests if m["kind"] == "trace_lane"]
    assert len(lane_manifests) == 1
    assert lane_manifests[0]["completeness"] == SourceCompleteness.BLOCKED.value
    # The safe endpoint label survives; the actual endpoint URL never enters the manifest.
    dumped = json.dumps(lane_manifests[0])
    assert "lf.example" not in dumped


# --------------------------------------------------------------------------- #
# Negative control: a partial import cannot be relabeled complete
# --------------------------------------------------------------------------- #


def test_partial_import_never_reads_as_complete(tmp_path: Path) -> None:
    ds = tmp_path / "d.jsonl"
    ds.write_text(
        json.dumps({"input": "a", "output": {"x": 1}}) + "\n" + "not json\n", encoding="utf-8"
    )
    cfg = {
        "run": {"id": "r"},
        "datasets": [{"path": "d.jsonl"}],
        "metrics": [_metric()],
    }
    record = run_config(RuntimeConfig.from_mapping(cfg), tmp_path)
    (manifest,) = record.source_manifests
    # Sensitivity: the malformed record forces PARTIAL — a consumer reading the typed field can
    # never present this source as complete.
    assert manifest["completeness"] == SourceCompleteness.PARTIAL.value
    assert manifest["completeness"] != SourceCompleteness.COMPLETE.value
