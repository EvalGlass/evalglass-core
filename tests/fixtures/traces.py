"""F-2 — trace-export fixtures (EG-AT0-4).

Writers for the three import shapes the runtime accepts — OpenTelemetry-export,
OpenInference-export, and local trace JSONL — each with a **malformed sibling**
(a span missing its output, which must become a diagnostic, never a silent drop).
The shapes match the real adapters (``LocalJsonlTraceSource`` /
``OpenConventionTraceSource``) so a round-trip test proves the fixtures are valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: A convention token each export carries (used by later vendor-leak checks).
_OTEL_TOKEN = "gen_ai.prompt"  # noqa: S105 — convention attribute key, not a secret
_OPENINFERENCE_TOKEN = "output.value"  # noqa: S105 — convention attribute key, not a secret


@dataclass(frozen=True)
class TraceFixture:
    """A written trace-export file + the metadata a test needs to load it."""

    path: Path
    fmt: str  # "local" | "opentelemetry" | "openinference"
    expected_count: int
    convention_token: str | None = None


def _otel_span(trace_id: str, prompt: str, completion: str | None) -> dict[str, object]:
    # The trace id lives at the span-record top level (``context.trace_id``); the
    # convention input/output keys live in ``attributes`` (flat dotted keys).
    attrs: dict[str, object] = {"gen_ai.prompt": prompt}
    if completion is not None:
        attrs["gen_ai.completion"] = completion
    return {"name": "llm", "context": {"trace_id": trace_id}, "attributes": attrs}


def _openinference_span(trace_id: str, value: str, output: str | None) -> dict[str, object]:
    attrs: dict[str, object] = {"input.value": value}
    if output is not None:
        attrs["output.value"] = output
    return {"name": "llm", "context": {"trace_id": trace_id}, "attributes": attrs}


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def write_otel_export(tmp_path: Path, *, name: str = "otel.jsonl") -> TraceFixture:
    path = tmp_path / name
    _write_jsonl(path, [_otel_span("t1", "2+2", "4"), _otel_span("t2", "3+3", "6")])
    return TraceFixture(
        path=path, fmt="opentelemetry", expected_count=2, convention_token=_OTEL_TOKEN
    )


def write_otel_export_malformed(tmp_path: Path, *, name: str = "otel_bad.jsonl") -> Path:
    path = tmp_path / name
    _write_jsonl(path, [_otel_span("t1", "2+2", None)])  # missing output → mapping incomplete
    return path


def write_openinference_export(tmp_path: Path, *, name: str = "oinf.jsonl") -> TraceFixture:
    path = tmp_path / name
    _write_jsonl(
        path,
        [_openinference_span("t1", "2+2", "4"), _openinference_span("t2", "3+3", "6")],
    )
    return TraceFixture(
        path=path, fmt="openinference", expected_count=2, convention_token=_OPENINFERENCE_TOKEN
    )


def write_openinference_export_malformed(tmp_path: Path, *, name: str = "oinf_bad.jsonl") -> Path:
    path = tmp_path / name
    _write_jsonl(path, [_openinference_span("t1", "2+2", None)])
    return path


def write_local_trace_jsonl(tmp_path: Path, *, name: str = "local.jsonl") -> TraceFixture:
    path = tmp_path / name
    _write_jsonl(
        path,
        [
            {"trace_id": "t1", "behavior": {"input": "2+2", "output": "4"}},
            {"trace_id": "t2", "behavior": {"input": "3+3", "output": "6"}},
        ],
    )
    return TraceFixture(path=path, fmt="local", expected_count=2)


def write_local_trace_jsonl_malformed(tmp_path: Path, *, name: str = "local_bad.jsonl") -> Path:
    path = tmp_path / name
    # A line that is not a JSON object → invalid record, surfaced as a diagnostic.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"trace_id": "t1"}\n["not", "an", "object"]\n', encoding="utf-8")
    return path


__all__ = [
    "TraceFixture",
    "write_local_trace_jsonl",
    "write_local_trace_jsonl_malformed",
    "write_openinference_export",
    "write_openinference_export_malformed",
    "write_otel_export",
    "write_otel_export_malformed",
]
