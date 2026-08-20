"""EGTS runtime workspace factory + isolation checker (EGTS-M1-1).

Every runtime proof scenario gets a **fresh, isolated** host workspace: an ``evals/`` tree with
its own config, datasets, traces, evaluators, reports, baselines, calibration, and result
directories, a stable ``fixture_id`` for evidence, and an explicit scenario-local environment
(no ambient credentials). Isolation is a non-negotiable (``tests/CLAUDE.md §4`` state
isolation): two scenarios must never share a workspace, and ``check_workspaces_isolated`` is
the checker whose negative control proves reused state fails.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tests.egts.checkers import CheckerError

_SUBDIRS = ("datasets", "traces", "evaluators", "reports", "baselines", "calibration", "results")


@dataclass(frozen=True)
class RuntimeWorkspace:
    """A fresh, isolated ``evals/`` host layout materialized for one runtime scenario."""

    fixture_id: str
    root: Path
    config_path: Path
    datasets_dir: Path
    traces_dir: Path
    evaluators_dir: Path
    reports_dir: Path
    baselines_dir: Path
    calibration_dir: Path
    result_dir: Path
    env: dict[str, str] = field(default_factory=dict)


def make_workspace(
    base: Path,
    fixture_id: str,
    *,
    config: str | None = None,
    datasets: Mapping[str, str] | None = None,
    traces: Mapping[str, str] | None = None,
    evaluators: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimeWorkspace:
    """Materialize a fresh ``evals/`` workspace under ``base/<fixture_id>/``.

    Each call writes into its own ``fixture_id`` subtree, so distinct scenarios are isolated by
    construction. ``env`` is an explicit scenario-local mapping — the host process environment
    (and any ambient credentials) is never inherited.
    """
    root = base / fixture_id / "evals"
    for sub in _SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    config_path = root / "evalglass.yaml"
    if config is not None:
        config_path.write_text(config, encoding="utf-8")
    for name, body in (datasets or {}).items():
        (root / "datasets" / name).write_text(body, encoding="utf-8")
    for name, body in (traces or {}).items():
        (root / "traces" / name).write_text(body, encoding="utf-8")
    for name, body in (evaluators or {}).items():
        (root / "evaluators" / name).write_text(body, encoding="utf-8")

    return RuntimeWorkspace(
        fixture_id=fixture_id,
        root=root,
        config_path=config_path,
        datasets_dir=root / "datasets",
        traces_dir=root / "traces",
        evaluators_dir=root / "evaluators",
        reports_dir=root / "reports",
        baselines_dir=root / "baselines",
        calibration_dir=root / "calibration",
        result_dir=root / "results",
        env=dict(env or {}),
    )


_MUTABLE_DIRS = (
    "datasets_dir",
    "traces_dir",
    "evaluators_dir",
    "reports_dir",
    "baselines_dir",
    "calibration_dir",
    "result_dir",
)


def check_workspaces_isolated(a: RuntimeWorkspace, b: RuntimeWorkspace) -> None:
    """Assert two workspaces share no state — the negative control proves reuse fails."""
    if a.fixture_id == b.fixture_id:
        raise CheckerError(f"workspaces reuse fixture_id {a.fixture_id!r}")
    a_root, b_root = a.root.resolve(), b.root.resolve()
    if a_root == b_root:
        raise CheckerError(f"workspaces share root {a_root}")
    if a_root in b_root.parents or b_root in a_root.parents:
        raise CheckerError(f"one workspace nests inside the other: {a_root} / {b_root}")
    # Every mutable workspace directory must be distinct, not just the result dir — the CLI
    # writes under reports/ by default, and baselines/calibration are scenario state too.
    b_paths = {getattr(b, name).resolve() for name in _MUTABLE_DIRS}
    for name in _MUTABLE_DIRS:
        if getattr(a, name).resolve() in b_paths:
            raise CheckerError(f"workspaces share a {name}: {getattr(a, name)}")
