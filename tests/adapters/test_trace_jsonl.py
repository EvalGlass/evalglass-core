"""Local JSONL TraceSource adapter (EG-M1-3a).

A local trace record normalizes into a vendor-neutral ``TraceEnvelope`` plus a call-level
``EvalUnit`` — the core never sees a raw/vendor trace shape (route fidelity). Per-record
``data_policy`` overrides the config default; provenance records the trace + line. A
malformed record becomes a ``Diagnostic`` (not a low score); a missing file is a setup error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
from evalglass.core import DataPolicy, Severity, TraceEnvelope, UnitKind
from evalglass.harness.config import TraceConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.ports import TraceSource


def _write(tmp_path: Path, lines: list[str]) -> None:
    (tmp_path / "t.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _source(tmp_path: Path, **over: object) -> LocalJsonlTraceSource:
    cfg = TraceConfig.from_mapping({"path": "t.jsonl", **over}, 0)
    return LocalJsonlTraceSource(cfg, root=tmp_path)


def test_normalizes_record_into_envelope_and_call_unit(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "behavior": {"input": "q", "output": "a"}})])
    read = _source(tmp_path, data_policy="permitted").read()
    assert read.diagnostics == []
    assert len(read.units) == 1
    tu = read.units[0]
    assert isinstance(tu.envelope, TraceEnvelope)
    assert tu.envelope.trace_id == "t1"
    assert tu.envelope.source == "local_jsonl"
    assert tu.envelope.behavior == {"input": "q", "output": "a"}
    assert tu.unit.kind is UnitKind.CALL
    assert tu.unit.trace_id == "t1"


def test_record_data_policy_overrides_config(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [json.dumps({"trace_id": "t1", "behavior": {"x": 1}, "data_policy": "forbidden"})],
    )
    read = _source(tmp_path, data_policy="permitted").read()
    assert read.units[0].envelope.data_policy is DataPolicy.FORBIDDEN


def test_config_data_policy_used_when_record_omits_it(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "behavior": {"x": 1}})])
    read = _source(tmp_path, data_policy="permitted").read()
    assert read.units[0].envelope.data_policy is DataPolicy.PERMITTED


def test_provenance_records_trace_and_line(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "behavior": {"x": 1}})])
    prov = _source(tmp_path).read().units[0].envelope.provenance
    assert prov.get("line") == 1


def test_explicit_unit_id_preserved(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [json.dumps({"trace_id": "t1", "unit_id": "u-9", "behavior": {"x": 1}})],
    )
    assert _source(tmp_path).read().units[0].unit.unit_id == "u-9"


def test_malformed_json_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, ["{ not json", json.dumps({"trace_id": "t1", "behavior": {"x": 1}})])
    read = _source(tmp_path).read()
    assert len(read.units) == 1
    assert read.diagnostics[0].code == "trace_invalid_json"
    assert read.diagnostics[0].severity is Severity.ERROR


def test_nan_constant_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, ['{"trace_id": "t1", "behavior": {"x": NaN}}'])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_invalid_json"


def test_non_mapping_record_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps([1, 2, 3])])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_invalid_record"


def test_missing_trace_id_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"behavior": {"x": 1}})])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_invalid_record"


def test_missing_or_non_object_behavior_yields_diagnostic(tmp_path: Path) -> None:
    _write(
        tmp_path, [json.dumps({"trace_id": "t1"}), json.dumps({"trace_id": "t2", "behavior": 5})]
    )
    read = _source(tmp_path).read()
    assert read.units == []
    assert {d.code for d in read.diagnostics} == {"trace_invalid_record"}
    assert len(read.diagnostics) == 2


def test_non_object_provenance_yields_diagnostic(tmp_path: Path) -> None:
    # provenance is merged by the adapter (the core parser never sees the raw value),
    # so a non-object provenance must fail closed here.
    _write(tmp_path, [json.dumps({"trace_id": "t1", "behavior": {"x": 1}, "provenance": [1, 2]})])
    read = _source(tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_invalid_record"


def test_blank_lines_ignored(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "behavior": {"x": 1}}), "", "  "])
    read = _source(tmp_path).read()
    assert len(read.units) == 1
    assert read.diagnostics == []


def test_missing_trace_file_is_setup_error(tmp_path: Path) -> None:
    cfg = TraceConfig.from_mapping({"path": "nope.jsonl"}, 0)
    with pytest.raises(SetupError) as exc:
        LocalJsonlTraceSource(cfg, root=tmp_path).read()
    assert exc.value.diagnostic.code == "trace_not_found"


def test_adapter_satisfies_tracesource_protocol(tmp_path: Path) -> None:
    _write(tmp_path, [json.dumps({"trace_id": "t1", "behavior": {"x": 1}})])
    assert isinstance(_source(tmp_path), TraceSource)
