"""`evalglass connect --from` CLI wiring (Epic B, B1): local import dispatch + fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from evalglass.harness.cli import main


def _metric() -> dict[str, object]:
    return {
        "name": "field_presence",
        "evaluator_ref": "field_presence@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0, 1],
    }


def _cfg(tmp_path: Path) -> Path:
    p = tmp_path / "evalglass.yaml"
    p.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    return p


def _export(tmp_path: Path) -> Path:
    p = tmp_path / "export.jsonl"
    p.write_text(
        json.dumps({"trace_id": "t0", "behavior": {"input": "hi", "output": "ok"}}) + "\n",
        encoding="utf-8",
    )
    return p


def test_cli_connect_import_adds_route(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _cfg(tmp_path)
    export = _export(tmp_path)
    rc = main(["connect", "--from", str(export), "--format", "local", "--config", str(cfg)])
    assert rc == 0
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert doc["traces"][0]["format"] == "local"
    out = capsys.readouterr().out.lower()
    assert "proposed" in out  # honest framing
    assert "informational" in out
    assert "next" in out  # points at the next command


def test_cli_connect_requires_exactly_one_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cfg(tmp_path)
    # Neither --from nor --live.
    assert main(["connect", "--config", str(cfg)]) != 0
    # Both at once.
    export = _export(tmp_path)
    rc = main(["connect", "--from", str(export), "--live", "langfuse", "--config", str(cfg)])
    assert rc != 0
    assert "exactly one" in capsys.readouterr().err.lower()


def test_cli_connect_import_missing_config_fails_without_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = _export(tmp_path)
    missing = tmp_path / "evals" / "evalglass.yaml"
    rc = main(["connect", "--from", str(export), "--config", str(missing)])
    assert rc != 0
    assert not missing.exists()


def test_cli_connect_import_init_creates_config(tmp_path: Path) -> None:
    export = _export(tmp_path)
    cfg = tmp_path / "evals" / "evalglass.yaml"
    rc = main(["connect", "--from", str(export), "--config", str(cfg), "--init"])
    assert rc == 0
    assert cfg.exists()
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert doc["metrics"]  # not lanes-only
    assert doc["traces"]


def test_cli_connect_import_bad_file_no_partial_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cfg(tmp_path)
    before = cfg.read_text(encoding="utf-8")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("nonsense\n", encoding="utf-8")
    rc = main(["connect", "--from", str(bad), "--config", str(cfg)])
    assert rc != 0
    assert cfg.read_text(encoding="utf-8") == before  # config untouched
