"""Local JSONL DatasetStore adapter (EG-M1-2).

The adapter turns a host-owned ``*.jsonl`` dataset into core ``Example`` objects, sources
dataset status/version/policy from the host config (never inferring or upgrading them —
"never silently validates host-owned truth"), and turns a malformed line into a
``Diagnostic`` rather than a low score or a crash. A missing dataset file is a setup error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.dataset_jsonl import LocalJsonlDatasetStore
from evalglass.core import DataPolicy, DatasetStatus, Severity, UnitKind
from evalglass.harness.config import DatasetConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.ports import DatasetStore


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _store(tmp_path: Path, **over: object) -> LocalJsonlDatasetStore:
    cfg = DatasetConfig.from_mapping({"path": "d.jsonl", **over}, 0)
    return LocalJsonlDatasetStore(cfg, root=tmp_path)


def test_reads_reference_and_non_reference_examples(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "d.jsonl",
        [
            json.dumps({"input": "2+2", "output": "4", "reference": "4"}),
            json.dumps({"input": "sky?", "output": "blue"}),  # non-reference
        ],
    )
    read = _store(tmp_path).read()
    assert len(read.examples) == 2
    assert read.diagnostics == []
    assert read.examples[0].reference == "4"
    assert read.examples[1].reference is None


def test_status_version_policy_come_from_config(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"input": "i", "output": "o"})])
    read = _store(tmp_path, status="validated", version="3", data_policy="permitted").read()
    assert read.status is DatasetStatus.VALIDATED
    assert read.version == "3"
    assert read.data_policy is DataPolicy.PERMITTED


def test_default_status_is_proposed_never_silently_validated(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"input": "i", "output": "o"})])
    read = _store(tmp_path).read()
    assert read.status is DatasetStatus.PROPOSED
    assert read.data_policy is DataPolicy.UNKNOWN


def test_examples_are_call_level_units(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"input": "i", "output": "o"})])
    unit = _store(tmp_path).read().examples[0].unit
    assert unit.kind is UnitKind.CALL


def test_explicit_example_id_preserved(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"id": "ex-7", "input": "i", "output": "o"})])
    assert _store(tmp_path).read().examples[0].example_id == "ex-7"


def test_malformed_json_line_yields_diagnostic_and_continues(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "d.jsonl",
        [
            json.dumps({"input": "a", "output": "1"}),
            "{ this is not json",
            json.dumps({"input": "b", "output": "2"}),
        ],
    )
    read = _store(tmp_path).read()
    assert len(read.examples) == 2  # the two good lines still load
    assert len(read.diagnostics) == 1
    diag = read.diagnostics[0]
    assert diag.code == "dataset_invalid_json"
    assert diag.severity is Severity.ERROR
    assert diag.location is not None
    assert ":2" in diag.location


def test_non_standard_json_constants_yield_diagnostic(tmp_path: Path) -> None:
    # json.loads accepts NaN/Infinity by default; those are not valid JSONL and would
    # leak non-finite floats into contracts. They must become an invalid-JSON diagnostic.
    _write(tmp_path, "d.jsonl", ['{"input": NaN, "output": "x"}'])
    read = _store(tmp_path).read()
    assert read.examples == []
    assert read.diagnostics[0].code == "dataset_invalid_json"
    read2 = _store(tmp_path)
    (tmp_path / "d.jsonl").write_text('{"input": 1, "output": Infinity}\n', encoding="utf-8")
    assert read2.read().diagnostics[0].code == "dataset_invalid_json"


def test_integer_example_id_is_accepted(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"id": 7, "input": "i", "output": "o"})])
    assert _store(tmp_path).read().examples[0].example_id == "7"


def test_empty_example_id_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"id": "", "input": "i", "output": "o"})])
    read = _store(tmp_path).read()
    assert read.examples == []
    assert read.diagnostics[0].code == "dataset_invalid_record"


def test_non_scalar_example_id_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"id": [1, 2], "input": "i", "output": "o"})])
    read = _store(tmp_path).read()
    assert read.examples == []
    assert read.diagnostics[0].code == "dataset_invalid_record"


def test_missing_input_yields_diagnostic(tmp_path: Path) -> None:
    # `input` is still required; only `output` became optional (EG-M2-1b, awaiting replay).
    _write(tmp_path, "d.jsonl", [json.dumps({"output": "o"})])  # no input
    read = _store(tmp_path).read()
    assert read.examples == []
    assert read.diagnostics[0].code == "dataset_invalid_record"


def test_missing_output_is_replayable_example_not_diagnostic(tmp_path: Path) -> None:
    # A record without `output` is a valid "awaiting replay" example (output=None), not malformed.
    _write(tmp_path, "d.jsonl", [json.dumps({"input": "a", "reference": "a"})])
    read = _store(tmp_path).read()
    assert read.diagnostics == []
    assert len(read.examples) == 1
    assert read.examples[0].output is None


def test_non_mapping_line_yields_diagnostic(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps([1, 2, 3])])
    read = _store(tmp_path).read()
    assert read.examples == []
    assert read.diagnostics[0].code == "dataset_invalid_record"


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "d.jsonl",
        [
            json.dumps({"input": "a", "output": "1"}),
            "",
            "   ",
            json.dumps({"input": "b", "output": "2"}),
        ],
    )
    read = _store(tmp_path).read()
    assert len(read.examples) == 2
    assert read.diagnostics == []


def test_missing_dataset_file_is_setup_error(tmp_path: Path) -> None:
    cfg = DatasetConfig.from_mapping({"path": "nope.jsonl"}, 0)
    store = LocalJsonlDatasetStore(cfg, root=tmp_path)
    with pytest.raises(SetupError) as exc:
        store.read()
    assert exc.value.diagnostic.code == "dataset_not_found"


def test_adapter_satisfies_datasetstore_protocol(tmp_path: Path) -> None:
    _write(tmp_path, "d.jsonl", [json.dumps({"input": "i", "output": "o"})])
    assert isinstance(_store(tmp_path), DatasetStore)
