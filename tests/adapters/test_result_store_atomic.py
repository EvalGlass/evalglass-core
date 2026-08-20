"""Atomic persistence + run verification (M7 T5c).

The ResultStore writes crash-safely and emits a manifest + completion marker so an
interrupted or hand-edited run cannot be adopted as a baseline.
See src/evalglass/adapters/result_store_fs.py and docs/TETA_REDESIGN.md §7.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.adapters.result_store_fs import FilesystemResultStore, verify_run
from evalglass.core.aggregation import aggregate
from evalglass.core.contracts import UnitKind
from evalglass.core.estimate import estimate
from evalglass.core.provenance import RunFingerprint
from evalglass.core.registry import Aggregation, Direction, Lens, MetricSpec, ScoreType
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreStatus, Validity
from evalglass.core.verdict import decide_verdict
from evalglass.harness.errors import SetupError


def _record() -> RunRecord:
    spec = MetricSpec(
        name="exact_match",
        version="1",
        lens=Lens.NON_REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref="exact_match@1",
        aggregation=Aggregation.RATE,
    )
    scores = [Score("exact_match", 1.0, ScoreStatus.SCORED, Validity.VALID, "1")]
    sc = Scorecard(
        verdict=decide_verdict([]),
        metrics=[aggregate(spec.name, scores, spec.aggregation)],
        authority={},
        estimates=[estimate(spec, scores)],
    )
    dims = {
        d: f"{d}-v1"
        for d in (
            "framework",
            "metric_spec",
            "evaluator",
            "dataset",
            "example",
            "evidence",
            "config",
            "policy",
            "authority",
            "baseline",
        )
    }
    return RunRecord(
        run_id="run-1", scorecard=sc, scores=scores, provenance=RunFingerprint.of(dims)
    )


def test_persist_writes_manifest_and_marker(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path).persist(_record())
    assert paths.runrecord.is_file()
    assert paths.scorecard.is_file()
    assert (paths.run_dir / "manifest.json").is_file()
    assert (paths.run_dir / "run.complete").is_file()
    # No temp files linger.
    assert not list(paths.run_dir.glob(".*.tmp"))
    verify_run(paths.run_dir)  # a fresh run verifies


def test_verify_fails_without_marker(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path).persist(_record())
    (paths.run_dir / "run.complete").unlink()
    with pytest.raises(SetupError, match="completion marker"):
        verify_run(paths.run_dir)


def test_verify_fails_on_tampered_artifact(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path).persist(_record())
    # Edit the scorecard after the run was marked complete.
    paths.scorecard.write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(SetupError, match="manifest digest"):
        verify_run(paths.run_dir)


def test_verify_fails_on_manifest_marker_mismatch(tmp_path: Path) -> None:
    paths = FilesystemResultStore(tmp_path).persist(_record())
    # Swap the manifest without updating the marker.
    (paths.run_dir / "manifest.json").write_text('{"schema":"x","files":{}}\n', encoding="utf-8")
    with pytest.raises(SetupError, match="does not match the manifest digest"):
        verify_run(paths.run_dir)


def test_repersist_refreshes_marker(tmp_path: Path) -> None:
    store = FilesystemResultStore(tmp_path)
    paths = store.persist(_record())
    store.persist(_record())  # a second run over the same id
    verify_run(paths.run_dir)  # still consistent (marker refreshed)
