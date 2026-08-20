"""Filesystem ``ResultStore`` adapter (EG-M1-5; atomic persistence M7 T5c).

Persists the primary machine artifacts — ``runrecord.json`` and ``scorecard.json`` — under
``<base>/<run-id>/``. It writes immutable typed data only: it never recomputes a verdict,
mutates authority, or promotes a baseline (baseline updates are an explicit M2 command). The
run-id is sanitized into a safe directory name so a host-supplied id cannot escape the output
tree.

Writes are crash-safe and integrity-checkable (M7 T5c): each artifact is written to a temp
file, fsynced, and atomically renamed into place, then a ``manifest.json`` records each file's
SHA-256 and a ``run.complete`` marker (holding the manifest digest) is written **last**. A
partial/interrupted write therefore never leaves a run that looks complete, and
:func:`verify_run` re-checks the marker + digests so a baseline promotion can accept only a
complete, internally consistent run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from evalglass.core import RunRecord
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.ports import ResultPaths

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MANIFEST = "manifest.json"
_MARKER = "run.complete"
_MANIFEST_SCHEMA = "evalglass.run-manifest/1"


class FilesystemResultStore:
    """A :class:`~evalglass.harness.ports.ResultStore` writing JSON under a base directory."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def persist(self, record: RunRecord) -> ResultPaths:
        safe_id = _UNSAFE.sub("_", record.run_id).strip("._") or "run"
        run_dir = self._base_dir / safe_id
        # Defense in depth beyond run-id sanitization: refuse to write through a pre-existing
        # symlink and confirm the resolved dir stays under the output base, so artifacts can
        # never be written outside the tree.
        if run_dir.is_symlink():
            raise SetupError(
                setup_diagnostic(
                    "result_dir_unsafe",
                    f"refusing to write through a symlinked result directory: {run_dir}",
                    location=str(run_dir),
                )
            )
        run_dir.mkdir(parents=True, exist_ok=True)
        base_resolved = self._base_dir.resolve()
        resolved = run_dir.resolve()
        if resolved != base_resolved and base_resolved not in resolved.parents:
            raise SetupError(
                setup_diagnostic(
                    "result_dir_unsafe",
                    f"result directory escapes the output base: {run_dir}",
                    location=str(run_dir),
                )
            )
        # A re-persist must not leave a stale "complete" marker while new files are written.
        (run_dir / _MARKER).unlink(missing_ok=True)

        runrecord = run_dir / "runrecord.json"
        scorecard = run_dir / "scorecard.json"
        rr_text = _dump(record.to_dict())
        sc_text = _dump(record.scorecard.to_dict())
        _atomic_write_text(runrecord, rr_text)
        _atomic_write_text(scorecard, sc_text)

        manifest = {
            "schema": _MANIFEST_SCHEMA,
            "files": {
                "runrecord.json": _sha256(rr_text),
                "scorecard.json": _sha256(sc_text),
            },
        }
        manifest_text = _dump(manifest)
        _atomic_write_text(run_dir / _MANIFEST, manifest_text)
        # Completion marker written LAST; it holds the manifest digest so a truncated
        # manifest can't be paired with a stale marker.
        _atomic_write_text(run_dir / _MARKER, _sha256(manifest_text) + "\n")
        return ResultPaths(run_dir=run_dir, runrecord=runrecord, scorecard=scorecard)


def verify_run(run_dir: Path) -> None:
    """Raise :class:`SetupError` unless ``run_dir`` is a complete, integrity-checked run.

    Checks the completion marker exists and matches the manifest digest, and that every
    file the manifest lists still hashes to its recorded SHA-256. Baseline promotion and
    the ``verify`` path use this so an interrupted or edited run cannot be adopted.
    """
    marker = run_dir / _MARKER
    manifest_path = run_dir / _MANIFEST
    if not marker.is_file():
        raise SetupError(
            setup_diagnostic(
                "run_incomplete",
                f"run has no completion marker (interrupted or partial write): {run_dir}",
                location=str(run_dir),
            )
        )
    if not manifest_path.is_file():
        raise SetupError(
            setup_diagnostic(
                "run_incomplete", f"run has no manifest: {run_dir}", location=str(run_dir)
            )
        )
    # Read both artifacts fail-closed: invalid UTF-8 raises UnicodeDecodeError (a ValueError), which
    # must become a typed setup error, not a raw traceback past the CLI's handlers.
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        marker_text = marker.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise SetupError(
            setup_diagnostic(
                "run_manifest_invalid",
                f"run manifest/marker is unreadable: {exc}",
                location=str(run_dir),
            )
        ) from exc
    if marker_text.strip() != _sha256(manifest_text):
        raise SetupError(
            setup_diagnostic(
                "run_manifest_mismatch",
                f"completion marker does not match the manifest digest: {run_dir}",
                location=str(run_dir),
            )
        )
    try:
        manifest = json.loads(manifest_text)
        files = manifest["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SetupError(
            setup_diagnostic(
                "run_manifest_invalid", f"run manifest is malformed: {exc}", location=str(run_dir)
            )
        ) from exc
    # A well-formed JSON manifest whose ``files`` is not an object (e.g. a list) would raise
    # AttributeError on ``.items()`` below — outside the guard — so reject it explicitly.
    if not isinstance(files, dict):
        raise SetupError(
            setup_diagnostic(
                "run_manifest_invalid",
                f"run manifest 'files' must be an object, got {type(files).__name__}",
                location=str(run_dir),
            )
        )
    for name, expected in files.items():
        target = run_dir / name
        if not target.is_file() or _sha256(target.read_text(encoding="utf-8")) != expected:
            raise SetupError(
                setup_diagnostic(
                    "run_artifact_tampered",
                    f"artifact {name!r} is missing or does not match its manifest digest",
                    location=str(target),
                )
            )


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` crash-safely: temp file -> fsync -> atomic rename.

    The file is created ``0o600`` (owner read/write only): run records, scorecards, and
    reports can carry host evaluation evidence, so they are not world-readable by default.
    """
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)  # atomic on the same filesystem


#: Public alias — the crash-safe writer, reused by the drift watcher (EG-P4) to persist its typed
#: sidecar artifact next to the run's other files with the same atomic guarantee.
atomic_write_text = _atomic_write_text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"
