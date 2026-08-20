"""Runtime workspace factory + isolation checker (EGTS-M1-1).

Proves every runtime scenario gets a fresh, isolated ``evals/`` workspace with an explicit
environment and a stable fixture id — and that the isolation checker fails closed when state
is reused (the mandatory negative control).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.egts.checkers import CheckerError
from tests.egts.workspace import check_workspaces_isolated, make_workspace


def test_workspace_materializes_full_layout(tmp_path: Path) -> None:
    ws = make_workspace(
        tmp_path,
        "fx-1",
        config="run:\n  id: x\n",
        datasets={"d.jsonl": '{"input":"a","output":"b"}\n'},
        traces={"t.jsonl": '{"trace_id":"t","behavior":{"output":"b"}}\n'},
        evaluators={"e.py": "x = 1\n"},
    )
    assert ws.config_path.is_file()
    assert (ws.datasets_dir / "d.jsonl").is_file()
    assert (ws.traces_dir / "t.jsonl").is_file()
    assert (ws.evaluators_dir / "e.py").is_file()
    for d in (ws.reports_dir, ws.baselines_dir, ws.calibration_dir, ws.result_dir):
        assert d.is_dir()


def test_fixture_id_and_explicit_env(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, "fx-2", env={"EVALGLASS_X": "1"})
    assert ws.fixture_id == "fx-2"
    assert ws.env == {"EVALGLASS_X": "1"}
    # default env is empty — never the ambient process environment / credentials
    assert make_workspace(tmp_path, "fx-3").env == {}


def test_distinct_workspaces_are_isolated(tmp_path: Path) -> None:
    a = make_workspace(tmp_path, "fx-a")
    b = make_workspace(tmp_path, "fx-b")
    check_workspaces_isolated(a, b)  # must not raise
    assert a.root != b.root
    assert a.result_dir != b.result_dir


def test_isolation_checker_fails_on_reused_state(tmp_path: Path) -> None:
    # Negative control: re-materializing the same fixture id reuses the same tree.
    a = make_workspace(tmp_path, "fx-same")
    b = make_workspace(tmp_path, "fx-same")
    with pytest.raises(CheckerError):
        check_workspaces_isolated(a, b)


@pytest.mark.parametrize("shared_dir", ["result_dir", "reports_dir", "baselines_dir"])
def test_isolation_checker_fails_on_any_shared_dir(tmp_path: Path, shared_dir: str) -> None:
    from dataclasses import replace

    a = make_workspace(tmp_path, "fx-x")
    b = make_workspace(tmp_path, "fx-y")
    shared = replace(b, **{shared_dir: getattr(a, shared_dir)})
    with pytest.raises(CheckerError):
        check_workspaces_isolated(a, shared)
