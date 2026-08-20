"""Run series index — immutable run identity and honest descriptive history (Epic E / E4; ADR 0061).

A fixed config run-id addresses the *latest* artifacts under ``reports/<run-id>/`` (that dir is
the mutable ``latest`` alias — reran, it is overwritten, so existing consumers/goldens see the new
run byte-for-byte as before). This module adds, alongside it, the durable identities a developer
tracking evaluations over time needs:

* ``series_id`` — the stable evaluation suite (defaults to the config run-id);
* ``run_id`` — a run's requested name;
* ``run_key`` — a content digest of the RunRecord, the run's unique immutable identity;
* an append-only, crash-safe, repairable **index** (``reports/.series/index.jsonl``) with one entry
  per completed run (digest, verdict, evaluability, examples, baseline identity); and
* an immutable, integrity-covered **snapshot** of each distinct run under
  ``reports/.series/runs/<run_key>/`` — so rerunning a fixed name never erases prior evidence.

Two honesty rules hold. The index is **descriptive**: the dashboard reads it for coverage history
(evaluability, example count over time) and never as a regression claim — a regression is only ever
the typed paired comparison (D4). And a duplicate digest is an explicit idempotent no-op: an
identical rerun does not append a second entry and never silently overwrites history. The index is
rebuildable from the verified snapshots (``repair``), so a lost or corrupt index invents nothing.

Effectful (filesystem) — a Runtime Harness concern, never imported by the effect-free core.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalglass.adapters.result_store_fs import atomic_write_text, verify_run
from evalglass.core import RunRecord
from evalglass.harness.errors import SetupError

_SERIES_DIR = ".series"
_INDEX = "index.jsonl"
_RUNS = "runs"
_MANIFEST = "manifest.json"
_MARKER = "run.complete"
_MANIFEST_SCHEMA = "evalglass.run-manifest/1"
_RUNRECORD = "runrecord.json"
_SCORECARD = "scorecard.json"


@dataclass(frozen=True)
class SeriesEntry:
    """One completed run's immutable descriptive record in a series index."""

    series_id: str
    run_id: str
    run_key: str
    verdict: str
    ci_should_fail: bool
    examples: int
    evaluability: float | None = None
    generated_at: str = ""
    baseline_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "series_id": self.series_id,
            "run_id": self.run_id,
            "run_key": self.run_key,
            "verdict": self.verdict,
            "ci_should_fail": self.ci_should_fail,
            "examples": self.examples,
        }
        if self.evaluability is not None:
            out["evaluability"] = self.evaluability
        if self.generated_at:
            out["generated_at"] = self.generated_at
        if self.baseline_run_id is not None:
            out["baseline_run_id"] = self.baseline_run_id
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SeriesEntry:
        return cls(
            series_id=str(data["series_id"]),
            run_id=str(data["run_id"]),
            run_key=str(data["run_key"]),
            verdict=str(data["verdict"]),
            ci_should_fail=bool(data["ci_should_fail"]),
            examples=int(data["examples"]),
            evaluability=(
                float(data["evaluability"]) if data.get("evaluability") is not None else None
            ),
            generated_at=str(data.get("generated_at", "")),
            baseline_run_id=(
                str(data["baseline_run_id"]) if data.get("baseline_run_id") is not None else None
            ),
        )

    def history_point(self) -> dict[str, Any]:
        """The descriptive point the progression chart plots (never a regression claim)."""
        point: dict[str, Any] = {"run_id": self.run_id, "examples": self.examples}
        if self.generated_at:
            point["generated_at"] = self.generated_at
        if self.evaluability is not None:
            point["evaluability"] = self.evaluability
        return point


def run_key_for(record: RunRecord) -> str:
    """A run's immutable identity: a content digest of its canonical RunRecord JSON."""
    canonical = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _evaluability(record: RunRecord) -> float | None:
    metrics = record.scorecard.metrics
    if not metrics:
        return None
    scored = sum(1 for m in metrics if m.value is not None and m.included_count > 0)
    return round(scored / len(metrics), 10)


def _examples(record: RunRecord) -> int:
    return len({s.example_id for s in record.scores if s.example_id})


def _baseline_run_id(record: RunRecord) -> str | None:
    comparison = record.scorecard.comparison
    return comparison.baseline_run_id if comparison is not None else None


def entry_for(record: RunRecord, *, series_id: str, generated_at: str = "") -> SeriesEntry:
    """The descriptive index entry for a completed run (pure — no I/O)."""
    return SeriesEntry(
        series_id=series_id,
        run_id=record.run_id,
        run_key=run_key_for(record),
        verdict=record.scorecard.verdict.verdict.value,
        ci_should_fail=record.scorecard.verdict.ci_should_fail,
        examples=_examples(record),
        evaluability=_evaluability(record),
        generated_at=generated_at,
        baseline_run_id=_baseline_run_id(record),
    )


def read_index(base_dir: Path) -> list[SeriesEntry]:
    """Every recorded entry, oldest first; a malformed line is skipped, never inventing an entry."""
    index_path = base_dir / _SERIES_DIR / _INDEX
    if not index_path.is_file():
        return []
    entries: list[SeriesEntry] = []
    for raw in index_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            entries.append(SeriesEntry.from_dict(json.loads(line)))
        except (ValueError, KeyError, TypeError):
            continue
    return entries


def _write_index(base_dir: Path, entries: list[SeriesEntry]) -> None:
    """Write the whole index atomically (temp -> fsync -> rename), so a crash never truncates it."""
    series_dir = base_dir / _SERIES_DIR
    series_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(e.to_dict(), sort_keys=True) + "\n" for e in entries)
    atomic_write_text(series_dir / _INDEX, body)


def _write_snapshot(base_dir: Path, record: RunRecord, run_key: str) -> Path:
    """Write an immutable, integrity-covered snapshot; an existing snapshot is left untouched."""
    snap = base_dir / _SERIES_DIR / _RUNS / run_key
    if (snap / _MARKER).is_file():
        return snap  # identical digest -> already captured; never overwrite immutable evidence
    snap.mkdir(parents=True, exist_ok=True)
    rr = json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n"
    sc = json.dumps(record.scorecard.to_dict(), indent=2, sort_keys=True) + "\n"
    atomic_write_text(snap / _RUNRECORD, rr)
    atomic_write_text(snap / _SCORECARD, sc)
    manifest = {
        "schema": _MANIFEST_SCHEMA,
        "files": {_RUNRECORD: _sha256(rr), _SCORECARD: _sha256(sc)},
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    atomic_write_text(snap / _MANIFEST, manifest_text)
    atomic_write_text(snap / _MARKER, _sha256(manifest_text) + "\n")  # completion marker last
    return snap


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_run(
    base_dir: Path, record: RunRecord, *, series_id: str, generated_at: str = ""
) -> list[dict[str, Any]]:
    """Snapshot the run, append its index entry idempotently, and return the series history points.

    Returns the descriptive history (this series' entries, oldest first) the dashboard plots. A
    duplicate ``run_key`` (an identical rerun) neither re-snapshots nor re-appends — history is
    append-only and never silently overwritten.
    """
    entry = entry_for(record, series_id=series_id, generated_at=generated_at)
    _write_snapshot(base_dir, record, entry.run_key)
    entries = read_index(base_dir)
    if not any(e.run_key == entry.run_key for e in entries):
        entries.append(entry)
        _write_index(base_dir, entries)
    return [e.history_point() for e in entries if e.series_id == series_id]


def previous_verified_run(base_dir: Path, series_id: str, *, before_key: str) -> Path | None:
    """The immediately previous verified snapshot in this series (never a pre-overwrite file).

    Walks the series' index backwards from ``before_key`` and returns the first snapshot that passes
    integrity verification, so a partial or tampered run is never selected as "previous".
    """
    entries = [e for e in read_index(base_dir) if e.series_id == series_id]
    keys = [e.run_key for e in entries]
    if before_key not in keys:
        return None
    for entry in reversed(entries[: keys.index(before_key)]):
        snap = base_dir / _SERIES_DIR / _RUNS / entry.run_key
        if _is_verified(snap):
            return snap
    return None


def _is_verified(run_dir: Path) -> bool:
    """Whether ``run_dir`` is a complete, integrity-checked snapshot (partial/tampered is not)."""
    try:
        verify_run(run_dir)
    except SetupError:
        return False
    return True


def repair_index(base_dir: Path) -> list[SeriesEntry]:
    """Rebuild the index from the verified snapshots on disk — inventing no entry (E4 AC9).

    A snapshot that fails integrity verification is skipped. Existing index order is preserved for
    known run_keys; recovered-but-unindexed snapshots are appended. The rebuilt index is written
    atomically and returned.
    """
    runs_dir = base_dir / _SERIES_DIR / _RUNS
    recovered: dict[str, SeriesEntry] = {}
    if runs_dir.is_dir():
        for snap in sorted(runs_dir.iterdir()):
            if not snap.is_dir() or not _is_verified(snap):
                continue
            try:
                data = json.loads((snap / _RUNRECORD).read_text(encoding="utf-8"))
                record = RunRecord.from_dict(data)
            except (ValueError, KeyError, TypeError, OSError):
                continue
            key = snap.name
            recovered[key] = entry_for(
                record, series_id=_recovered_series(base_dir, key, record), generated_at=""
            )
    ordered: list[SeriesEntry] = []
    seen: set[str] = set()
    for existing in read_index(base_dir):
        if existing.run_key in recovered and existing.run_key not in seen:
            ordered.append(recovered.pop(existing.run_key))
            seen.add(existing.run_key)
    ordered.extend(recovered[k] for k in sorted(recovered))
    _write_index(base_dir, ordered)
    return ordered


def _recovered_series(base_dir: Path, run_key: str, record: RunRecord) -> str:
    """The series id for a recovered snapshot: its indexed id if known, else the run id."""
    for entry in read_index(base_dir):
        if entry.run_key == run_key:
            return entry.series_id
    return record.run_id
