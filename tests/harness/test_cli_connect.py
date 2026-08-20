"""`evalglass connect --live` CLI wiring (EG-P2-3): dispatch, honest help, fail-closed errors."""

from __future__ import annotations

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


def test_cli_connect_scaffolds_lane(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _cfg(tmp_path)
    rc = main(
        ["connect", "--live", "langfuse", "--config", str(cfg), "--endpoint", "https://lf.example"]
    )
    assert rc == 0
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert doc["lanes"][0]["name"] == "langfuse-trace"
    assert doc["lanes"][0]["data_policy"] == "unknown"  # fail-closed default
    out = capsys.readouterr().out.lower()
    assert "proposed" in out  # honest framing on success
    assert "opt-in" in out


def test_cli_connect_credentials_are_env_refs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    rc = main(
        [
            "connect",
            "--live",
            "langfuse",
            "--config",
            str(cfg),
            "--credentials",
            "public_key=LF_PUB",
            "secret_key=LF_SEC",
        ]
    )
    assert rc == 0
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert doc["lanes"][0]["options"]["credentials"] == {
        "public_key": "LF_PUB",
        "secret_key": "LF_SEC",
    }


def test_cli_connect_unknown_platform_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cfg(tmp_path)
    rc = main(["connect", "--live", "bogus", "--config", str(cfg)])
    assert rc != 0  # fail-closed
    err = capsys.readouterr().err.lower()
    assert "langfuse" in err  # lists valid platforms
    assert "phoenix" in err
    assert "langsmith" in err


def test_cli_connect_rejects_literal_secret_without_echo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _cfg(tmp_path)
    rc = main(
        [
            "connect",
            "--live",
            "langfuse",
            "--config",
            str(cfg),
            "--credentials",
            "public_key=inline-literal-not-an-env-name",
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "inline-literal-not-an-env-name" not in err  # the rejected literal must never leak


def test_cli_connect_help_is_honest(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["connect", "--help"])
    out = capsys.readouterr().out.lower()
    assert "opt-in" in out
    assert "proposed" in out
    assert "extra" in out  # names the required per-platform extra
    # No overclaiming language.
    assert "production" not in out
    assert "guarantee" not in out
