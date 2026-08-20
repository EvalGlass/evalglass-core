"""Declarative evidence assembly (Epic B, B4).

A host often needs to join trace calls, parser outcomes, and application state — which live in
separate records — into evaluation examples, and today writes a bespoke dataset builder per host.
This module is a small, declarative, host-owned workbench that does it generically:

* named sources — a local dataset/trace JSONL export, or an opt-in argv snapshot command;
* typed joins with declared cardinality (``one_to_one`` / ``one_to_many`` / ``optional_one``), each
  cardinality violation a distinct, typed diagnostic;
* field projection from dotted source paths, preserving behavior layers and fail-closed on a
  conflicting output field (a field can never be silently overwritten from two sources);
* a versioned ``EvidenceAssemblyManifest`` with per-field lineage, reconciled counts, diagnostics,
  a content-addressed config digest, and an output digest.

There is no expression language and no second scoring engine: the output is an ordinary Example-
shaped JSONL that routes through the normal dataset contract. Determinism is explicit — the same
inputs and config produce a byte-identical output and digest. Snapshot commands run without a shell,
argv-only, timeout-bounded, root-contained, and only after a data-policy check.

Stdlib + core only; effects (file read, subprocess) are the host's, gated and typed.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import subprocess  # nosec B404 — argv-only, shell=False snapshot command (host opt-in)
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from evalglass.core import DataPolicy, Diagnostic, Severity
from evalglass.harness._safe_fs import checked_target
from evalglass.harness.coverage import SourceCompleteness, derive_completeness
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.governance import GovernanceError

_EGRESS_OK = frozenset({DataPolicy.PERMITTED, DataPolicy.REDACTED})


class SourceKind(enum.StrEnum):
    """A named assembly input."""

    DATASET = "dataset"
    TRACE = "trace"
    SNAPSHOT = "snapshot"  # an opt-in argv command emitting a JSON list on stdout


class Cardinality(enum.StrEnum):
    """The declared multiplicity of a join's right side per left record."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    OPTIONAL_ONE = "optional_one"


def _require(mapping: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise SetupError(setup_diagnostic("assembly_config", f"{ctx}: missing '{key}'"))
    return mapping[key]


@dataclass(frozen=True)
class AssemblySource:
    """One named input record set."""

    name: str
    kind: SourceKind
    path: str | None = None
    command: tuple[str, ...] = ()
    timeout_s: float = 30.0
    data_policy: DataPolicy = DataPolicy.UNKNOWN

    @classmethod
    def from_mapping(cls, data: Any, idx: int) -> Self:
        ctx = f"evidence_pipeline.sources[{idx}]"
        if not isinstance(data, Mapping):
            raise SetupError(setup_diagnostic("assembly_config", f"{ctx}: must be a mapping"))
        name = str(_require(data, "name", ctx))
        try:
            kind = SourceKind(_require(data, "kind", ctx))
        except ValueError as exc:
            raise SetupError(
                setup_diagnostic("assembly_config", f"{ctx}: unknown kind {data.get('kind')!r}")
            ) from exc
        command_raw = data.get("command", [])
        if kind is SourceKind.SNAPSHOT:
            if not isinstance(command_raw, list) or not command_raw:
                raise SetupError(
                    setup_diagnostic(
                        "assembly_config", f"{ctx}: snapshot needs a non-empty command"
                    )
                )
            if not all(isinstance(a, str) and a for a in command_raw):
                raise SetupError(
                    setup_diagnostic("assembly_config", f"{ctx}: command items must be strings")
                )
        elif not data.get("path"):
            raise SetupError(
                setup_diagnostic("assembly_config", f"{ctx}: {kind.value} needs a path")
            )
        return cls(
            name=name,
            kind=kind,
            path=str(data["path"]) if data.get("path") else None,
            command=tuple(str(a) for a in command_raw),
            timeout_s=float(data.get("timeout_s", 30.0)),
            data_policy=DataPolicy(data.get("data_policy", "unknown")),
        )


@dataclass(frozen=True)
class AssemblyJoin:
    """A declared join between two sources: ``<src>.<dotted.path>`` keys plus a cardinality."""

    left: str
    right: str
    cardinality: Cardinality

    @classmethod
    def from_mapping(cls, data: Any, idx: int) -> Self:
        ctx = f"evidence_pipeline.joins[{idx}]"
        if not isinstance(data, Mapping):
            raise SetupError(setup_diagnostic("assembly_config", f"{ctx}: must be a mapping"))
        try:
            cardinality = Cardinality(data.get("cardinality", "one_to_one"))
        except ValueError as exc:
            raise SetupError(
                setup_diagnostic("assembly_config", f"{ctx}: unknown cardinality")
            ) from exc
        return cls(
            left=str(_require(data, "left", ctx)),
            right=str(_require(data, "right", ctx)),
            cardinality=cardinality,
        )


@dataclass(frozen=True)
class EvidencePipeline:
    """A whole declarative assembly: named sources, joins, and an output field projection."""

    sources: tuple[AssemblySource, ...]
    joins: tuple[AssemblyJoin, ...]
    project: Mapping[str, str]  # output field -> "<source>.<dotted.path>"

    @classmethod
    def from_mapping(cls, data: Any) -> Self:
        if not isinstance(data, Mapping):
            raise SetupError(
                setup_diagnostic("assembly_config", "evidence_pipeline: must be a mapping")
            )
        sources = tuple(
            AssemblySource.from_mapping(s, i)
            for i, s in enumerate(_as_list(data, "sources", "evidence_pipeline"))
        )
        if not sources:
            raise SetupError(setup_diagnostic("assembly_config", "evidence_pipeline: no sources"))
        names = [s.name for s in sources]
        if len(set(names)) != len(names):
            raise SetupError(
                setup_diagnostic("assembly_config", "evidence_pipeline: duplicate source name")
            )
        joins = tuple(
            AssemblyJoin.from_mapping(j, i)
            for i, j in enumerate(
                data.get("joins", []) if isinstance(data.get("joins"), list) else []
            )
        )
        project = data.get("project", {})
        if not isinstance(project, Mapping) or not project:
            raise SetupError(
                setup_diagnostic("assembly_config", "evidence_pipeline: 'project' required")
            )
        if "example_id" not in project:
            raise SetupError(
                setup_diagnostic(
                    "assembly_config", "evidence_pipeline: 'project' must map example_id"
                )
            )
        return cls(
            sources=sources, joins=joins, project={str(k): str(v) for k, v in project.items()}
        )

    def config_digest(self) -> str:
        payload = {
            "sources": [
                {"name": s.name, "kind": s.kind.value, "path": s.path, "command": list(s.command)}
                for s in self.sources
            ],
            "joins": [
                {"left": j.left, "right": j.right, "cardinality": j.cardinality.value}
                for j in self.joins
            ],
            "project": dict(self.project),
        }
        return _digest(payload)


def _as_list(data: Mapping[str, Any], key: str, ctx: str) -> list[Any]:
    raw = data.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SetupError(setup_diagnostic("assembly_config", f"{ctx}: '{key}' must be a list"))
    return raw


@dataclass(frozen=True)
class EvidenceAssemblyManifest:
    """Lineage + reconciled counts + integrity for one assembly run."""

    source_counts: Mapping[str, int]
    output_count: int
    completeness: SourceCompleteness
    lineage: Mapping[str, str]
    config_digest: str
    output_digest: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": "evalglass.evidence-assembly/1",
            "source_counts": dict(self.source_counts),
            "output_count": self.output_count,
            "completeness": self.completeness.value,
            "lineage": dict(self.lineage),
            "config_digest": self.config_digest,
            "output_digest": self.output_digest,
        }
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        return out


def _digest(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    )


def _resolve_path(record: Mapping[str, Any], dotted: str) -> tuple[Any, bool]:
    """Resolve ``a.b.c`` within a record; returns ``(value, found)``."""
    cur: Any = record
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None, False
    return cur, True


def _split_ref(ref: str) -> tuple[str, str]:
    source, _, path = ref.partition(".")
    return source, path


def _read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    from evalglass.adapters._jsonl import iter_json_lines, read_text

    text = read_text(
        path,
        not_found_code="assembly_source",
        unreadable_code="assembly_source",
        kind="assembly source",
    )
    records: list[Mapping[str, Any]] = []
    for jl in iter_json_lines(text):
        if jl.error is None and isinstance(jl.record, Mapping):
            records.append(jl.record)
    return records


def _run_snapshot(source: AssemblySource, root: Path) -> list[Mapping[str, Any]]:
    """Run an opt-in snapshot command (argv, shell=False), parse a JSON list from stdout."""
    if source.data_policy not in _EGRESS_OK:
        raise SetupError(
            setup_diagnostic(
                "assembly_policy",
                f"snapshot source {source.name!r} data policy {source.data_policy.value} "
                "forbids running the command",
            )
        )
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603 - argv-only, shell=False, host command
            list(source.command),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=source.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SetupError(
            setup_diagnostic("assembly_snapshot", f"snapshot {source.name!r} timed out")
        ) from exc
    if proc.returncode != 0:
        raise SetupError(
            setup_diagnostic(
                "assembly_snapshot", f"snapshot {source.name!r} exited {proc.returncode}"
            )
        )
    try:
        parsed = json.loads(proc.stdout)
    except ValueError as exc:
        raise SetupError(
            setup_diagnostic("assembly_snapshot", f"snapshot {source.name!r} stdout not JSON")
        ) from exc
    if not isinstance(parsed, list):
        raise SetupError(
            setup_diagnostic("assembly_snapshot", f"snapshot {source.name!r} must emit a JSON list")
        )
    return [r for r in parsed if isinstance(r, Mapping)]


def _load_source(source: AssemblySource, root: Path) -> list[Mapping[str, Any]]:
    if source.kind is SourceKind.SNAPSHOT:
        return _run_snapshot(source, root)
    if source.path is None:  # guaranteed by from_mapping; a defensive typed guard, not an assert
        raise SetupError(setup_diagnostic("assembly_config", f"source {source.name!r} has no path"))
    # A host-config source path must stay inside the pipeline's own tree — a `../../etc/...` path or
    # a symlinked component is refused before the read (fail-closed path validation).
    return _read_jsonl(_safe(root, root / source.path, what=f"source {source.name!r}"))


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.WARNING, message=message)


def _apply_join(
    rows: list[dict[str, Mapping[str, Any]]],
    join: AssemblyJoin,
    records: Mapping[str, list[Mapping[str, Any]]],
    diagnostics: list[Diagnostic],
) -> list[dict[str, Mapping[str, Any]]]:
    """Attach the ``right`` source to each row by key, honoring the declared cardinality."""
    left_src, left_path = _split_ref(join.left)
    right_src, right_path = _split_ref(join.right)
    index: dict[Any, list[Mapping[str, Any]]] = {}
    for rec in records.get(right_src, []):
        key, found = _resolve_path(rec, right_path)
        if found:
            index.setdefault(_hashable(key), []).append(rec)
    out: list[dict[str, Mapping[str, Any]]] = []
    for row in rows:
        base = row.get(left_src)
        key, found = (_resolve_path(base, left_path)) if base is not None else (None, False)
        matches = index.get(_hashable(key), []) if found else []
        out.extend(_join_row(row, right_src, matches, join, diagnostics))
    return out


def _join_row(
    row: dict[str, Mapping[str, Any]],
    right_src: str,
    matches: list[Mapping[str, Any]],
    join: AssemblyJoin,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Mapping[str, Any]]]:
    n = len(matches)
    if join.cardinality is Cardinality.ONE_TO_MANY:
        if n == 0:
            diagnostics.append(
                _diag("assembly_join_missing", f"{join.right}: no match for a {join.left}")
            )
            return []
        return [{**row, right_src: m} for m in matches]
    if n > 1:
        diagnostics.append(
            _diag("assembly_join_ambiguous", f"{join.right}: {n} matches for a {join.left}")
        )
        return []
    if n == 0:
        if join.cardinality is Cardinality.OPTIONAL_ONE:
            return [row]  # optional — keep the left, right source simply absent
        diagnostics.append(
            _diag("assembly_join_missing", f"{join.right}: no match for a {join.left}")
        )
        return []
    return [{**row, right_src: matches[0]}]


def _hashable(value: Any) -> Any:
    """A hashable key for join indexing (dict/list keys collapse to their canonical JSON)."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return json.dumps(value, sort_keys=True)


def assemble(
    pipeline: EvidencePipeline, root: Path
) -> tuple[list[dict[str, Any]], EvidenceAssemblyManifest]:
    """Load sources, join them by declared cardinality, project fields, and build the manifest.

    Deterministic: output rows are sorted by ``example_id`` and the manifest carries a config digest
    and an output digest, so unchanged inputs+config reproduce a byte-identical result. A bad
    cardinality is a distinct diagnostic and drops the offending row (the assembly reads partial) —
    never a silent or fabricated join.
    """
    records = {s.name: _load_source(s, root) for s in pipeline.sources}
    diagnostics: list[Diagnostic] = []
    rows: list[dict[str, Mapping[str, Any]]] = [
        {pipeline.sources[0].name: rec} for rec in records[pipeline.sources[0].name]
    ]
    for join in pipeline.joins:
        rows = _apply_join(rows, join, records, diagnostics)

    output: list[dict[str, Any]] = []
    for row in rows:
        record = _project_row(row, pipeline.project, diagnostics)
        if record is not None:
            output.append(record)
    output.sort(key=lambda r: str(r.get("example_id", "")))

    source_counts = {name: len(recs) for name, recs in records.items()}
    completeness = derive_completeness(
        records_seen=len(records[pipeline.sources[0].name]),
        units_emitted=len(output),
        rejected=len(diagnostics),
    )
    manifest = EvidenceAssemblyManifest(
        source_counts=source_counts,
        output_count=len(output),
        completeness=completeness,
        lineage=dict(pipeline.project),
        config_digest=pipeline.config_digest(),
        output_digest=_digest(output),
        diagnostics=diagnostics,
    )
    return output, manifest


def _project_row(
    row: Mapping[str, Mapping[str, Any]],
    project: Mapping[str, str],
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    """Project one joined row into an Example-shaped record; a missing example_id drops the row."""
    record: dict[str, Any] = {}
    for out_field, ref in project.items():
        src, path = _split_ref(ref)
        source_record = row.get(src)
        if source_record is None:
            continue  # an optional source absent for this row → the field is honestly absent
        value, found = _resolve_path(source_record, path)
        if found:
            record[out_field] = value
    example_id = record.get("example_id")
    if example_id is None or (isinstance(example_id, str) and not example_id):
        diagnostics.append(_diag("assembly_no_example_id", "row projected no stable example_id"))
        return None
    record["example_id"] = str(example_id)
    return record


def _safe(base: Path, path: Path, *, what: str) -> Path:
    """``checked_target`` mapping a path-validation refusal to a typed assembly ``SetupError``."""
    try:
        return checked_target(base, path, what=what)
    except GovernanceError as exc:
        raise SetupError(setup_diagnostic("assembly_path", str(exc))) from exc


def write_assembly(output: list[dict[str, Any]], out_path: Path) -> Path:
    """Write the (already-validated) assembled Example JSONL atomically; return the path written."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.parent / f"{out_path.name}.tmp"
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in output), encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path


def load_pipeline(path: Path) -> EvidencePipeline:
    """Load an ``evidence_pipeline`` document (its own file, or an ``evidence_pipeline:`` key)."""
    import yaml  # type: ignore[import-untyped]

    safe = _safe(path.resolve().parent, path, what="pipeline config")
    try:
        doc = yaml.safe_load(safe.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError(setup_diagnostic("assembly_config", f"cannot read {path}: {exc}")) from exc
    if isinstance(doc, Mapping) and "evidence_pipeline" in doc:
        doc = doc["evidence_pipeline"]
    return EvidencePipeline.from_mapping(doc)


def run_assembly(config_path: Path, out_path: Path) -> EvidenceAssemblyManifest:
    """Assemble from a pipeline config; write the dataset + ``<out>.manifest.json`` (host-owned).

    The assembled dataset and its manifest are host-owned evaluation evidence and are confined to
    the pipeline config's own directory tree (a ``--out`` that would escape it, or pass through a
    symlink, is refused). The sources join under that same tree.
    """
    root = config_path.resolve().parent
    pipeline = load_pipeline(config_path)
    output, manifest = assemble(pipeline, root)
    safe_out = _safe(root, out_path, what="assembly output")
    write_assembly(output, safe_out)
    manifest_path = safe_out.parent / f"{safe_out.name}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
