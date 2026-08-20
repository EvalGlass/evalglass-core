"""Local JSONL ``DatasetStore`` adapter (EG-M1-2).

Reads a host-owned ``*.jsonl`` dataset into core :class:`~evalglass.core.Example` objects.
Each line is one record: required ``input``; optional ``output`` (absent = awaiting host
replay, EG-M2-1b), ``reference`` (its presence is what makes an example reference vs
non-reference), ``id``, ``context``, ``metadata``. A malformed line becomes a
:class:`~evalglass.core.Diagnostic` and the read continues — one bad record never sinks the
dataset or becomes a low score. Dataset
status/version/policy come from the host config unchanged (never silently validated); a
missing dataset file is a setup error.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evalglass.core import Diagnostic, EvalUnit, Example, Severity, UnitKind
from evalglass.harness.config import DatasetConfig
from evalglass.harness.coverage import SourceImportManifest, derive_completeness
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.ports import DatasetRead


def _reject_constant(token: str) -> object:
    """Make ``json.loads`` reject the non-standard NaN/Infinity tokens it accepts by default."""
    raise ValueError(f"non-standard JSON constant {token!r}")


class LocalJsonlDatasetStore:
    """A :class:`~evalglass.harness.ports.DatasetStore` backed by a local JSONL file."""

    def __init__(self, config: DatasetConfig, root: Path) -> None:
        self._config = config
        self._root = root

    def read(self) -> DatasetRead:
        path = self._root / self._config.path
        text = self._read_text(path)
        examples: list[Example] = []
        diagnostics: list[Diagnostic] = []
        records_seen = 0
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            records_seen += 1
            loc = f"{self._config.path}:{lineno}"
            try:
                record = json.loads(line, parse_constant=_reject_constant)
            except ValueError as exc:  # JSONDecodeError ⊂ ValueError; also NaN/Infinity tokens
                diagnostics.append(
                    Diagnostic(
                        code="dataset_invalid_json",
                        severity=Severity.ERROR,
                        message=f"invalid JSON: {exc}",
                        location=loc,
                    )
                )
                continue
            built = self._example(record, lineno, loc)
            if isinstance(built, Example):
                examples.append(built)
            else:
                diagnostics.append(built)
        manifest = SourceImportManifest(
            source=self._config.name,
            kind="dataset",
            adapter="local_jsonl",
            data_policy=self._config.data_policy,
            completeness=derive_completeness(
                records_seen=records_seen,
                units_emitted=len(examples),
                rejected=len(diagnostics),
            ),
            records_seen=records_seen,
            units_emitted=len(examples),
            rejected=len(diagnostics),
            availability={
                "input": bool(examples),
                "application_output": any(e.output is not None for e in examples),
                "reference": any(e.reference is not None for e in examples),
                "stable_ids": bool(examples),
            },
            diagnostics=list(diagnostics),
            provenance={"status": self._config.status.value, "version": self._config.version},
        )
        return DatasetRead(
            name=self._config.name,
            status=self._config.status,
            version=self._config.version,
            data_policy=self._config.data_policy,
            examples=examples,
            diagnostics=diagnostics,
            manifest=manifest,
        )

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SetupError(
                setup_diagnostic(
                    "dataset_not_found", f"dataset file not found: {path}", location=str(path)
                )
            ) from exc
        except UnicodeDecodeError as exc:
            raise SetupError(
                setup_diagnostic(
                    "dataset_unreadable",
                    f"dataset file is not valid UTF-8: {path}",
                    location=str(path),
                )
            ) from exc
        except OSError as exc:
            raise SetupError(
                setup_diagnostic(
                    "dataset_unreadable", f"cannot read dataset {path}: {exc}", location=str(path)
                )
            ) from exc

    def _example(self, record: Any, lineno: int, loc: str) -> Example | Diagnostic:
        def bad(message: str) -> Diagnostic:
            return Diagnostic(
                code="dataset_invalid_record",
                severity=Severity.ERROR,
                message=message,
                location=loc,
            )

        if not isinstance(record, Mapping):
            return bad(f"dataset record must be a JSON object, got {type(record).__name__}")
        # `input` is required; `output` is optional — an absent output means "awaiting replay"
        # (M2 EG-M2-1b). Without a configured task it stays None and the example is non_evaluable
        # (excluded honestly), never a fabricated pass.
        if "input" not in record:
            return bad("dataset record must declare 'input'")
        context = record.get("context", {})
        metadata = record.get("metadata", {})
        if not isinstance(context, Mapping):
            return bad("dataset record 'context' must be an object")
        if not isinstance(metadata, Mapping):
            return bad("dataset record 'metadata' must be an object")
        if "id" in record or "example_id" in record:
            raw_id = record.get("id", record.get("example_id"))
            if isinstance(raw_id, bool) or not isinstance(raw_id, str | int):
                return bad("dataset record 'id' must be a string or integer")
            example_id = str(raw_id).strip()
            if not example_id:
                return bad("dataset record 'id' must not be empty")
        else:
            example_id = f"{self._config.name}#{lineno}"
        return Example(
            example_id=example_id,
            input=record["input"],
            output=record.get("output"),
            unit=EvalUnit(
                unit_id=f"{self._config.name}#{lineno}",
                kind=UnitKind.CALL,
                trace_id=f"dataset:{self._config.name}",
            ),
            reference=record.get("reference"),
            context=dict(context),
            metadata=dict(metadata),
            provenance={"dataset": self._config.name, "line": lineno},
        )
