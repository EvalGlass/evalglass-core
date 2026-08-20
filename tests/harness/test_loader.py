"""Config file loading at the effect boundary (EG-M1-1).

``load_config`` is the only place that touches the filesystem and YAML. Every
failure becomes a typed :class:`SetupError` carrying a :class:`Diagnostic` — a
config problem is a *setup* error, never a host quality failure or a traceback
(build contract §8). These tests pin the failure taxonomy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.core import Severity
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.loader import load_config

_VALID = """
run:
  id: demo
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
"""


def test_load_valid_yaml(tmp_path: Path) -> None:
    p = tmp_path / "evalglass.yaml"
    p.write_text(_VALID, encoding="utf-8")
    cfg = load_config(p)
    assert isinstance(cfg, RuntimeConfig)
    assert cfg.run_id == "demo"


def test_missing_file_is_setup_error(tmp_path: Path) -> None:
    with pytest.raises(SetupError) as exc:
        load_config(tmp_path / "nope.yaml")
    assert exc.value.diagnostic.code == "config_not_found"
    assert exc.value.diagnostic.severity is Severity.ERROR


def test_malformed_yaml_is_setup_error(tmp_path: Path) -> None:
    p = tmp_path / "evalglass.yaml"
    p.write_text("metrics: [unclosed\n", encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_config(p)
    assert exc.value.diagnostic.code == "config_parse_error"


def test_invalid_schema_is_setup_error(tmp_path: Path) -> None:
    # Well-formed YAML, invalid config (no metrics) → setup error, not a crash.
    p = tmp_path / "evalglass.yaml"
    p.write_text("run:\n  id: x\n", encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_config(p)
    assert exc.value.diagnostic.code == "config_invalid"


def test_invalid_utf8_is_setup_error(tmp_path: Path) -> None:
    # An undecodable config must be a setup error, not a UnicodeDecodeError traceback.
    p = tmp_path / "evalglass.yaml"
    p.write_bytes(b"\xff\xfe metrics: []\n")
    with pytest.raises(SetupError) as exc:
        load_config(p)
    assert exc.value.diagnostic.code == "config_unreadable"


def test_yaml_top_level_not_mapping_is_setup_error(tmp_path: Path) -> None:
    p = tmp_path / "evalglass.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_config(p)
    assert exc.value.diagnostic.code == "config_invalid"
