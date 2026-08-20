"""Filesystem ResultStore adapter (EG-M1-5).

Persists the primary machine artifacts and round-trips them through the core contracts.
It writes only — no baseline promotion, no authority mutation — and sanitizes the run-id so
a host-supplied id cannot escape the output tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.adapters.result_store_fs import FilesystemResultStore
from evalglass.core import RunRecord, Scorecard
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.ports import ResultStore
from evalglass.harness.runner import run_config


def _record(tmp_path: Path, run_id: str = "run-1") -> RunRecord:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = RuntimeConfig.from_mapping(
        {
            "run": {"id": run_id},
            "datasets": [{"path": "d.jsonl"}],
            "metrics": [
                {
                    "name": "exact_match",
                    "evaluator_ref": "exact_match@1",
                    "lens": "reference",
                    "score_type": "binary",
                    "dataset": "d.jsonl",
                }
            ],
        }
    )
    return run_config(cfg, root=tmp_path)


def test_persists_and_round_trips(tmp_path: Path) -> None:
    record = _record(tmp_path)
    paths = FilesystemResultStore(tmp_path / "out").persist(record)
    assert paths.runrecord.is_file()
    assert paths.scorecard.is_file()
    assert RunRecord.from_dict(json.loads(paths.runrecord.read_text(encoding="utf-8"))) == record
    assert (
        Scorecard.from_dict(json.loads(paths.scorecard.read_text(encoding="utf-8")))
        == record.scorecard
    )


def test_run_dir_named_by_run_id(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path / "out").persist(_record(tmp_path, "demo-7"))
    assert paths.run_dir.name == "demo-7"


def test_unsafe_run_id_is_sanitized(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path / "out").persist(_record(tmp_path, "../../escape"))
    # the run dir stays inside the output base — no traversal
    assert (tmp_path / "out") in paths.run_dir.parents
    assert "/" not in paths.run_dir.name


def test_does_not_write_a_baseline(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path / "out").persist(_record(tmp_path))
    assert not (paths.run_dir / "baseline.json").exists()


def test_symlinked_result_dir_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "out"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "run-1").symlink_to(outside, target_is_directory=True)  # pre-existing escape
    with pytest.raises(SetupError) as exc:
        FilesystemResultStore(base).persist(_record(tmp_path))
    assert exc.value.diagnostic.code == "result_dir_unsafe"


def test_satisfies_resultstore_protocol(tmp_path: Path) -> None:
    assert isinstance(FilesystemResultStore(tmp_path / "out"), ResultStore)
