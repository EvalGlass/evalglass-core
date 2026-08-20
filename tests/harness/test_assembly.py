"""Declarative evidence assembly (Epic B, B4).

Sensitivity: cardinality violations (missing / duplicate / ambiguous) produce distinct diagnostics
and drop the row; a snapshot command is argv-only, timeout-bounded, and policy-gated. Specificity: a
clean join projects lineage-tracked fields, is reproducible (identical output + digest), and routes
through the ordinary dataset contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evalglass.harness.assembly import EvidencePipeline, assemble, run_assembly
from evalglass.harness.errors import SetupError


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _pipeline(cardinality: str = "one_to_one") -> EvidencePipeline:
    return EvidencePipeline.from_mapping(
        {
            "sources": [
                {"name": "calls", "kind": "trace", "path": "calls.jsonl"},
                {"name": "state", "kind": "dataset", "path": "state.jsonl"},
            ],
            "joins": [{"left": "calls.req", "right": "state.req", "cardinality": cardinality}],
            "project": {
                "example_id": "calls.id",
                "input": "calls.behavior.input",
                "output": "calls.behavior.output",
                "reference": "state.expected",
            },
        }
    )


def _sources(tmp_path: Path, state_rows: list[dict[str, object]]) -> None:
    _write(
        tmp_path / "calls.jsonl",
        [{"id": "c1", "req": "r1", "behavior": {"input": "i", "output": "o"}}],
    )
    _write(tmp_path / "state.jsonl", state_rows)


# --------------------------------------------------------------------------- #
# Happy path: join + projection + lineage + determinism
# --------------------------------------------------------------------------- #


def test_one_to_one_join_projects_fields_with_lineage(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "r1", "expected": "gold"}])
    output, manifest = assemble(_pipeline(), tmp_path)
    assert output == [{"example_id": "c1", "input": "i", "output": "o", "reference": "gold"}]
    assert manifest.lineage["reference"] == "state.expected"  # every field has source lineage
    assert manifest.completeness.value == "complete_within_declared_scope"


def test_reproducible_output_and_digest(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "r1", "expected": "gold"}])
    out1, man1 = assemble(_pipeline(), tmp_path)
    out2, man2 = assemble(_pipeline(), tmp_path)
    assert out1 == out2
    assert man1.output_digest == man2.output_digest
    assert man1.config_digest == man2.config_digest


def test_changed_config_changes_digest(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "r1", "expected": "gold"}])
    _, man_a = assemble(_pipeline("one_to_one"), tmp_path)
    _, man_b = assemble(_pipeline("optional_one"), tmp_path)
    assert man_a.config_digest != man_b.config_digest  # cardinality is score-determining config


# --------------------------------------------------------------------------- #
# Cardinality matrix — distinct diagnostics, row dropped
# --------------------------------------------------------------------------- #


def test_missing_match_is_a_distinct_diagnostic(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "OTHER", "expected": "gold"}])  # no r1 match
    output, manifest = assemble(_pipeline("one_to_one"), tmp_path)
    assert output == []  # the unmatched row is dropped, not fabricated
    assert any(d.code == "assembly_join_missing" for d in manifest.diagnostics)
    assert manifest.completeness.value == "partial"


def test_ambiguous_match_is_a_distinct_diagnostic(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "r1", "expected": "a"}, {"req": "r1", "expected": "b"}])
    output, manifest = assemble(_pipeline("one_to_one"), tmp_path)
    assert output == []  # 2 matches for a one_to_one → ambiguous, dropped
    assert any(d.code == "assembly_join_ambiguous" for d in manifest.diagnostics)


def test_optional_one_keeps_left_when_no_match(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "OTHER", "expected": "gold"}])
    output, _ = assemble(_pipeline("optional_one"), tmp_path)
    # The left row is kept; the reference field is honestly absent (no fabricated value).
    assert output == [{"example_id": "c1", "input": "i", "output": "o"}]


def test_one_to_many_fans_out(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "r1", "expected": "a"}, {"req": "r1", "expected": "b"}])
    output, _ = assemble(_pipeline("one_to_many"), tmp_path)
    assert len(output) == 2
    assert {r["reference"] for r in output} == {"a", "b"}


def test_row_without_example_id_is_dropped(tmp_path: Path) -> None:
    _write(tmp_path / "calls.jsonl", [{"req": "r1", "behavior": {"input": "i"}}])  # no id
    _write(tmp_path / "state.jsonl", [{"req": "r1", "expected": "g"}])
    output, manifest = assemble(_pipeline(), tmp_path)
    assert output == []
    assert any(d.code == "assembly_no_example_id" for d in manifest.diagnostics)


# --------------------------------------------------------------------------- #
# Snapshot command safety
# --------------------------------------------------------------------------- #


def test_snapshot_command_forbidden_policy_fails_closed(tmp_path: Path) -> None:
    pipeline = EvidencePipeline.from_mapping(
        {
            "sources": [
                {
                    "name": "state",
                    "kind": "snapshot",
                    "command": [sys.executable, "-c", "print('[]')"],
                    "data_policy": "forbidden",
                }
            ],
            "project": {"example_id": "state.id"},
        }
    )
    with pytest.raises(SetupError, match="forbids running"):
        assemble(pipeline, tmp_path)


def test_snapshot_command_runs_argv_only_and_projects(tmp_path: Path) -> None:
    script = tmp_path / "snap.py"
    script.write_text(
        "import json;print(json.dumps([{'id':'s1','expected':'gold'}]))", encoding="utf-8"
    )
    pipeline = EvidencePipeline.from_mapping(
        {
            "sources": [
                {
                    "name": "state",
                    "kind": "snapshot",
                    "command": [sys.executable, "snap.py"],
                    "data_policy": "permitted",
                }
            ],
            "project": {"example_id": "state.id", "reference": "state.expected"},
        }
    )
    output, _ = assemble(pipeline, tmp_path)
    assert output == [{"example_id": "s1", "reference": "gold"}]


def test_source_path_traversal_is_refused(tmp_path: Path) -> None:
    # A pipeline config source path that escapes the config tree is refused before any read.
    (tmp_path / "evals").mkdir()
    secret = tmp_path / "secret.jsonl"
    secret.write_text('{"input": "x"}\n', encoding="utf-8")
    pipeline = EvidencePipeline.from_mapping(
        {
            "sources": [{"name": "calls", "kind": "dataset", "path": "../secret.jsonl"}],
            "project": {"example_id": "calls.id"},
        }
    )
    with pytest.raises(SetupError, match="escapes"):
        assemble(pipeline, tmp_path / "evals")


def test_snapshot_nonzero_exit_fails_closed(tmp_path: Path) -> None:
    pipeline = EvidencePipeline.from_mapping(
        {
            "sources": [
                {
                    "name": "state",
                    "kind": "snapshot",
                    "command": [sys.executable, "-c", "import sys;sys.exit(3)"],
                    "data_policy": "permitted",
                }
            ],
            "project": {"example_id": "state.id"},
        }
    )
    with pytest.raises(SetupError, match="exited 3"):
        assemble(pipeline, tmp_path)


# --------------------------------------------------------------------------- #
# CLI-level: write dataset + manifest; routes through the ordinary dataset contract
# --------------------------------------------------------------------------- #


def test_run_assembly_writes_dataset_and_manifest(tmp_path: Path) -> None:
    _sources(tmp_path, [{"req": "r1", "expected": "gold"}])
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(
        json.dumps(
            {
                "sources": [
                    {"name": "calls", "kind": "trace", "path": "calls.jsonl"},
                    {"name": "state", "kind": "dataset", "path": "state.jsonl"},
                ],
                "joins": [{"left": "calls.req", "right": "state.req", "cardinality": "one_to_one"}],
                "project": {"example_id": "calls.id", "reference": "state.expected"},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "assembled.jsonl"
    manifest = run_assembly(cfg, out)
    assert out.is_file()
    # The output is an ordinary Example JSONL — one JSON object per line.
    rows = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"example_id": "c1", "reference": "gold"}]
    manifest_path = tmp_path / "assembled.jsonl.manifest.json"
    assert manifest_path.is_file()
    assert json.loads(manifest_path.read_text())["schema"] == "evalglass.evidence-assembly/1"
    assert manifest.output_count == 1
