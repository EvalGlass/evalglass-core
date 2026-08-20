"""TaskConfig — typed host replay command at the config boundary (EG-M2-1a).

``task:`` is host-owned truth: the host declares the exact argv (no shell) and a timeout.
Parsing fails closed (the M0 lesson) — a missing/empty/non-list argv or a non-positive timeout
is a setup error, never a silently-ignored or shell-interpreted command.
"""

from __future__ import annotations

import pytest

from evalglass.core import ContractError
from evalglass.harness.config import RuntimeConfig, TaskConfig

_METRIC = {
    "name": "m",
    "evaluator_ref": "exact_match@1",
    "lens": "reference",
    "score_type": "binary",
}


def test_valid_task_block() -> None:
    tc = TaskConfig.from_mapping({"argv": ["python", "host.py"], "timeout_s": 5})
    assert tc.argv == ["python", "host.py"]
    assert tc.timeout_s == pytest.approx(5.0)


def test_default_timeout() -> None:
    tc = TaskConfig.from_mapping({"argv": ["python", "host.py"]})
    assert tc.timeout_s == pytest.approx(30.0)


@pytest.mark.parametrize(
    "bad",
    [
        {},  # missing argv
        {"argv": []},  # empty argv
        {"argv": "python host.py"},  # not a list (would be shell-ish)
        {"argv": ["python", 3]},  # non-string item
        {"argv": ["python", ""]},  # empty-string item
        {"argv": ["python"], "timeout_s": 0},  # non-positive
        {"argv": ["python"], "timeout_s": -1},
        {"argv": ["python"], "timeout_s": "x"},  # not a number
        {"argv": ["python"], "timeout_s": True},  # bool is not a number
    ],
)
def test_malformed_task_block_fails_closed(bad: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        TaskConfig.from_mapping(bad)


def test_runtime_config_parses_task() -> None:
    cfg = RuntimeConfig.from_mapping(
        {"metrics": [_METRIC], "task": {"argv": ["python", "host.py"], "timeout_s": 10}}
    )
    assert cfg.task is not None
    assert cfg.task.argv == ["python", "host.py"]


def test_runtime_config_without_task_is_none() -> None:
    cfg = RuntimeConfig.from_mapping({"metrics": [_METRIC]})
    assert cfg.task is None


def test_runtime_config_present_null_task_fails_closed() -> None:
    # A present `task:` key with null/non-mapping is malformed config, not "no replay".
    with pytest.raises(ContractError):
        RuntimeConfig.from_mapping({"metrics": [_METRIC], "task": None})
