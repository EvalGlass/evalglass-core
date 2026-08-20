"""Behavior-layer preservation across trace normalization (Epic B, B3).

Raw model output, application-visible output, and parser diagnostics stay DISTINCT and separately
addressable; a parser-rejected span (raw present, application output absent) is evidence with its
diagnostics, never a dropped record or a fabricated zero; and an output-only span is byte-identical
to before (no richer layer requested).
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.adapters._span_mapping import behavior_from_attributes
from evalglass.adapters.trace_open_convention import OpenConventionTraceSource
from evalglass.harness.config import TraceConfig, TraceFormat


def _read(tmp_path: Path, rows: list[dict[str, object]]) -> object:
    p = tmp_path / "spans.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    cfg = TraceConfig(path="spans.jsonl", name="s", fmt=TraceFormat.OPENINFERENCE)
    return OpenConventionTraceSource(cfg, tmp_path).read()


# --------------------------------------------------------------------------- #
# behavior_from_attributes (the connector / span-mapping path)
# --------------------------------------------------------------------------- #


def test_raw_and_application_output_are_distinct() -> None:
    behavior = behavior_from_attributes(
        {"output.value": {"answer": "ok"}, "llm.output.raw": '{"answer": "ok", "extra": 1}'}
    )
    assert behavior is not None
    assert behavior["output"] == {"answer": "ok"}  # application-visible, unchanged
    assert behavior["raw_output"] == '{"answer": "ok", "extra": 1}'  # raw model output, distinct
    assert behavior["output"] != behavior["raw_output"]


def test_parser_rejected_span_is_evidence_not_dropped() -> None:
    # No application output (the parser rejected it) — raw model output + diagnostics remain.
    behavior = behavior_from_attributes(
        {
            "llm.output.raw": "not-valid-json-the-app-rejected",
            "evalglass.parser_diagnostics": ["json decode error at char 0"],
        }
    )
    assert behavior is not None  # NOT dropped
    assert "output" not in behavior  # application output honestly absent (→ non_evaluable, not 0.0)
    assert behavior["raw_output"] == "not-valid-json-the-app-rejected"
    assert behavior["parser_diagnostics"] == ["json decode error at char 0"]


def test_output_only_span_is_unchanged() -> None:
    behavior = behavior_from_attributes({"output.value": "hello", "input.value": "hi"})
    assert behavior == {"output": "hello", "input": "hi"}  # no new keys when no richer layer


def test_span_with_no_evaluable_evidence_is_none() -> None:
    assert behavior_from_attributes({"input.value": "hi"}) is None


# --------------------------------------------------------------------------- #
# Open-convention JSONL route
# --------------------------------------------------------------------------- #


def test_jsonl_preserves_layers_and_maps_parser_failure(tmp_path: Path) -> None:
    read = _read(
        tmp_path,
        [
            {
                "span_id": "s1",
                "attributes": {
                    "output.value": {"ok": True},
                    "llm.output.raw": "raw-1",
                },
            },
            {
                "span_id": "s2",
                "attributes": {
                    "llm.output.raw": "raw-2-rejected",
                    "evalglass.parser_diagnostics": ["rejected"],
                },
            },
        ],
    )
    units = read.units  # type: ignore[attr-defined]
    assert len(units) == 2  # the parser-failure span maps too (not dropped)
    b1 = units[0].envelope.behavior
    assert b1["output"] == {"ok": True}
    assert b1["raw_output"] == "raw-1"
    b2 = units[1].envelope.behavior
    assert "output" not in b2
    assert b2["raw_output"] == "raw-2-rejected"
    # The coverage manifest reports both raw-output and parser-diagnostics availability (B2xB3).
    m = read.manifest  # type: ignore[attr-defined]
    assert m is not None
    assert m.availability["raw_model_output"] is True
    assert m.availability["parser_diagnostics"] is True


def test_jsonl_output_only_still_maps(tmp_path: Path) -> None:
    read = _read(tmp_path, [{"span_id": "s1", "attributes": {"output.value": "hi"}}])
    units = read.units  # type: ignore[attr-defined]
    assert len(units) == 1
    assert units[0].envelope.behavior == {"output": "hi"}
