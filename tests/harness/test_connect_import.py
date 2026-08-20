"""Local trace import + fail-closed connect config semantics (Epic B, story B1).

Sensitivity: a local export is imported as a first-class ``traces:`` route with no live
credentials; a missing config fails closed unless ``--init`` is asked for; an invalid import
never writes a partial config. Specificity: an existing config, host keys, and the live-scaffold
path keep working, and re-importing is idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from evalglass.harness import connect
from evalglass.harness.config import RuntimeConfig


def _metric() -> dict[str, object]:
    return {
        "name": "field_presence",
        "evaluator_ref": "field_presence@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0, 1],
    }


def _write_local_export(path: Path, rows: int = 2) -> None:
    lines = [
        json.dumps({"trace_id": f"t{i}", "behavior": {"input": f"in{i}", "output": f"out{i}"}})
        for i in range(rows)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Local import — the first-class offline path (no credentials, no SDK)
# --------------------------------------------------------------------------- #


def test_local_import_adds_trace_route(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    export = tmp_path / "export.jsonl"
    _write_local_export(export)

    result = connect.apply_import(cfg, export, fmt="local")

    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "metrics" in doc  # host key preserved
    traces = doc["traces"]
    assert len(traces) == 1
    assert traces[0]["format"] == "local"
    # The written path resolves back to the export file relative to the config directory.
    assert (cfg.parent / traces[0]["path"]).resolve() == export.resolve()
    # The result reports what was imported and stays informational (a trace route can't gate).
    assert result["records"] >= 2


def test_local_import_needs_no_credentials(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    export = tmp_path / "export.jsonl"
    _write_local_export(export)
    connect.apply_import(cfg, export, fmt="local")
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    # No lane, no credentials block — a local import is not a live pull.
    assert "lanes" not in doc


def test_local_import_path_is_config_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "project"
    (run_dir / "evals").mkdir(parents=True)
    cfg = run_dir / "evals" / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    export = run_dir / "evals" / "traces" / "export.jsonl"
    export.parent.mkdir(parents=True)
    _write_local_export(export)
    # cwd is deliberately NOT the config directory.
    monkeypatch.chdir(tmp_path)
    connect.apply_import(cfg, export, fmt="local")
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    stored = doc["traces"][0]["path"]
    assert not Path(stored).is_absolute()  # stored relative to the config dir, not cwd
    assert (cfg.parent / stored).resolve() == export.resolve()


def test_local_import_is_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    export = tmp_path / "export.jsonl"
    _write_local_export(export)
    connect.apply_import(cfg, export, fmt="local")
    connect.apply_import(cfg, export, fmt="local")  # re-run must not duplicate
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert len(doc["traces"]) == 1


def test_local_import_preserves_host_keys_and_other_traces(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "metrics": [_metric()],
                "datasets": [{"path": "d.jsonl"}],
                "traces": [{"path": "other.jsonl", "format": "openinference"}],
                "custom_host_key": {"keep": True},
            }
        ),
        encoding="utf-8",
    )
    export = tmp_path / "export.jsonl"
    _write_local_export(export)
    connect.apply_import(cfg, export, fmt="local")
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert doc["datasets"] == [{"path": "d.jsonl"}]
    assert doc["custom_host_key"] == {"keep": True}
    names = {t["path"] for t in doc["traces"]}
    assert "other.jsonl" in names  # unrelated trace preserved
    assert len(doc["traces"]) == 2


# --------------------------------------------------------------------------- #
# Fail-closed: missing config, invalid import, no partial writes
# --------------------------------------------------------------------------- #


def test_missing_config_fails_without_init(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    export = tmp_path / "export.jsonl"
    _write_local_export(export)
    with pytest.raises(connect.ConnectError):
        connect.apply_import(cfg, export, fmt="local")  # no --init
    assert not cfg.exists()  # nothing written


def test_init_creates_conservative_informational_config(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    export = tmp_path / "export.jsonl"
    _write_local_export(export)
    connect.apply_import(cfg, export, fmt="local", init=True)
    assert cfg.exists()
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    parsed = RuntimeConfig.from_mapping(doc)  # loads
    # It is not a lanes-only document: it has metrics and the imported trace.
    assert parsed.metrics
    assert parsed.traces
    # Conservative: nothing is configured to gate.
    assert all(m.metric_status.value != "gating" for m in parsed.metrics)


def test_invalid_import_file_no_partial_write(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    original = {"metrics": [_metric()]}
    cfg.write_text(yaml.safe_dump(original), encoding="utf-8")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("this is not json at all\n{", encoding="utf-8")
    with pytest.raises(connect.ConnectError):
        connect.apply_import(cfg, bad, fmt="local")
    # Config is byte-untouched — no traces route added on a failed import.
    assert yaml.safe_load(cfg.read_text(encoding="utf-8")) == original


def test_missing_import_file_fails_closed(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    with pytest.raises(connect.ConnectError):
        connect.apply_import(cfg, tmp_path / "nope.jsonl", fmt="local")


def test_empty_import_file_fails_closed(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(connect.ConnectError):
        connect.apply_import(cfg, empty, fmt="local")


def test_unknown_format_fails_closed(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    export = tmp_path / "export.jsonl"
    _write_local_export(export)
    with pytest.raises(connect.ConnectError):
        connect.apply_import(cfg, export, fmt="not_a_format")


# --------------------------------------------------------------------------- #
# Live scaffold path: back-compat + the now-fail-closed missing-config rule
# --------------------------------------------------------------------------- #


def test_live_connect_still_scaffolds_on_existing_config(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    connect.apply_connect(cfg, "langfuse", endpoint="https://lf.example")
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert [ln["name"] for ln in doc["lanes"]] == ["langfuse-trace"]


def test_live_connect_missing_config_fails_without_init(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    with pytest.raises(connect.ConnectError):
        connect.apply_connect(cfg, "langfuse")  # previously started empty — now fail-closed
    assert not cfg.exists()


def test_live_connect_init_creates_informational_config(tmp_path: Path) -> None:
    cfg = tmp_path / "evalglass.yaml"
    connect.apply_connect(cfg, "langfuse", init=True)
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    parsed = RuntimeConfig.from_mapping(doc)
    assert parsed.metrics  # not lanes-only
    assert parsed.lanes
    assert parsed.lanes[0].name == "langfuse-trace"
