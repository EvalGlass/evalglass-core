"""Slice 14 (VG-P2-5): --debug observability trace.

A non-authoritative trace (routing rationale, family x claim coverage, evidence
classification + materialized adjacent artifacts) written to a sink (stderr for
the CLI). It never changes the status, exit code, or validator.result.json — it
only explains how the gate reached its verdict, for the first real M1 runs.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from scripts.adapter import run_adapter
from scripts.contracts import Status
from scripts.debug import build_trace, render_trace
from scripts.index import EvidenceIndex
from scripts.router import route
from scripts.runner import FAMILY_REGISTRY, run_validation
from scripts.validator import main


def _pack(**over) -> dict:
    base = {
        "schema_version": "validator.evidence.v1",
        "checkpoint": "EG.step-14.debug",
        "source_boundary": {"product": ["sc"], "external_contracts": ["rep"]},
        "claims": [
            {
                "id": "c1",
                "text": "report matches verdict",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc", "rep"],
            }
        ],
        "artifacts": [
            {
                "id": "sc",
                "kind": "scorecard",
                "authority": "product",
                "content": {"verdict": "pass"},
            },
            {
                "id": "rep",
                "kind": "report",
                "authority": "external",
                "content": {"claimed_status": "pass"},
            },
        ],
    }
    base.update(over)
    return base


# --- structured trace -------------------------------------------------------


def test_build_trace_structure() -> None:
    pack = _pack()
    index = EvidenceIndex.build(pack)
    router_result = route(index.pack)
    result = run_validation(pack)
    trace = build_trace(
        index=index,
        router_result=router_result,
        findings=result.findings,
        registry=FAMILY_REGISTRY,
        checkpoint="EG.step-14.debug",
    )
    assert trace["checkpoint"] == "EG.step-14.debug"
    assert "authority_verdict" in trace["registry"]
    assert trace["routing"]["status"] == "PASS"
    assert any(
        f["family_id"] == "authority_verdict" and "c1" in f["claim_ids"]
        for f in trace["routing"]["families"]
    )
    assert trace["evidence"]["by_authority"]["product"] == ["sc"]
    assert any(
        c["family_id"] == "authority_verdict" and c["claim_id"] == "c1" for c in trace["coverage"]
    )


def test_render_trace_has_sections() -> None:
    index = EvidenceIndex.build(_pack())
    trace = build_trace(
        index=index,
        router_result=route(index.pack),
        findings=run_validation(_pack()).findings,
        registry=FAMILY_REGISTRY,
        checkpoint="cp",
    )
    text = render_trace(trace)
    for marker in ("routing", "coverage", "evidence", "authority_verdict", "c1"):
        assert marker in text


def test_build_trace_is_deterministic() -> None:
    index = EvidenceIndex.build(_pack())
    rr = route(index.pack)
    findings = run_validation(_pack()).findings
    a = build_trace(
        index=index, router_result=rr, findings=findings, registry=FAMILY_REGISTRY, checkpoint="cp"
    )
    b = build_trace(
        index=index, router_result=rr, findings=findings, registry=FAMILY_REGISTRY, checkpoint="cp"
    )
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --- trace_sink on the pipeline (never changes the result) ------------------


def test_run_validation_trace_sink_writes_without_changing_result() -> None:
    pack = _pack()
    plain = run_validation(pack)
    sink = io.StringIO()
    traced = run_validation(pack, trace_sink=sink)
    assert traced.to_dict() == plain.to_dict()  # result unchanged
    out = sink.getvalue()
    assert "routing" in out
    assert "coverage" in out


def test_trace_surfaces_runner_blockers() -> None:
    # A routed-but-unimplemented family is BLOCKED at the runner; the trace must
    # show that blocker, not look clean while the verdict is BLOCKED.
    sink = io.StringIO()
    result = run_validation(_pack(), registry={}, trace_sink=sink)
    assert result.status is Status.BLOCKED
    out = sink.getvalue()
    assert "blocked_on" in out
    assert "authority_verdict" in out  # the unimplemented family is named


def test_run_validation_no_sink_is_silent() -> None:
    # Default: no trace produced (nothing to assert beyond it not raising).
    assert run_validation(_pack()).status is Status.PASS


def test_run_adapter_trace_includes_materialized_adjacent() -> None:
    pack = _pack(
        scan_gate_result={"status": "PASS"},
        claims=[
            {
                "id": "c1",
                "text": "verdict holds given a clean scan",
                "expected_families": ["authority_verdict"],
                "required_artifacts": ["sc", "rep", "scan_gate_result"],
            }
        ],
    )
    sink = io.StringIO()
    result, _ = run_adapter(pack, trace_sink=sink)
    assert result.status is Status.PASS
    assert "scan_gate_result" in sink.getvalue()


# --- CLI --debug ------------------------------------------------------------


def _write(tmp_path: Path, data: dict) -> Path:
    fp = tmp_path / "pack.json"
    fp.write_text(json.dumps(data), encoding="utf-8")
    return fp


def test_cli_debug_writes_trace_to_stderr_only(tmp_path, capsys) -> None:
    pack = _write(tmp_path, _pack())
    out = tmp_path / "r.json"
    rc = main(["run", "--evidence-pack", str(pack), "--debug", "--json", str(out)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "routing" in captured.err  # trace on stderr
    assert "routing" not in captured.out  # stdout stays the status summary
    # the authoritative JSON is unaffected by --debug
    debug_json = json.loads(out.read_text())
    main(["run", "--evidence-pack", str(pack), "--json", str(out)])
    assert json.loads(out.read_text()) == debug_json


def test_cli_debug_does_not_change_exit_code(tmp_path, capsys) -> None:
    bad = _pack(
        claims=[{"id": "c1", "text": "x", "required_artifacts": ["sc"]}]
    )  # unroutable -> BLOCKED
    pack = _write(tmp_path, bad)
    rc_plain = main(["run", "--evidence-pack", str(pack)])
    rc_debug = main(["run", "--evidence-pack", str(pack), "--debug"])
    assert rc_plain == rc_debug == 2


def test_cli_debug_on_unreadable_pack_still_blocks(tmp_path, capsys) -> None:
    rc = main(["run", "--evidence-pack", str(tmp_path / "missing.json"), "--debug"])
    assert rc == 2
