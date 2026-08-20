"""EG-MDU-5 — runtime robustness: PyYAML guard + warning-free module entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from evalglass.harness import loader
from evalglass.harness.errors import SetupError


def test_missing_pyyaml_is_a_setup_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text("run:\n  id: x\n", encoding="utf-8")
    monkeypatch.setattr(loader, "yaml", None)
    with pytest.raises(SetupError) as exc:
        loader.load_config(cfg)
    assert exc.value.diagnostic.code == "pyyaml_missing"


def test_harness_module_entrypoint_runs_without_runpy_warning() -> None:
    # `python -m evalglass.harness` goes through __main__.py, so cli is never run as __main__ and
    # the benign runpy "found in sys.modules" RuntimeWarning does not fire. Turn it into an error.
    result = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-m", "evalglass.harness", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "RuntimeWarning" not in result.stderr
