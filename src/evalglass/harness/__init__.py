"""Runtime Harness — effectful orchestration around the Evaluation Core.

Effects performed here (file I/O, network, subprocess, judge calls) must be
visible, testable, and behind ports owned by the runtime. See CLAUDE.md §4.
"""

from __future__ import annotations

from typing import Any

from evalglass.harness.config import (
    DatasetConfig,
    MetricConfig,
    RuntimeConfig,
    TaskConfig,
    TraceConfig,
    TraceFormat,
)
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.evaluator_loader import load_evaluator
from evalglass.harness.loader import load_config
from evalglass.harness.ports import (
    DatasetRead,
    DatasetStore,
    ResultPaths,
    ResultStore,
    ScoreSink,
    TaskRequest,
    TaskResult,
    TaskRunner,
    TraceRead,
    TraceSource,
    TraceUnit,
)
from evalglass.harness.prepare import example_from_trace
from evalglass.harness.report import MarkdownScoreSink, TerminalScoreSink

# NOTE: ``runner.run_config`` is intentionally *not* re-exported here. It imports the
# adapters, which import ``evalglass.harness.config`` — re-exporting it from the package
# __init__ would create an import cycle. Import it as ``evalglass.harness.runner.run_config``.


def __getattr__(name: str) -> Any:
    # ``cli`` is exposed lazily (PEP 562) rather than imported at package-import time. An eager
    # ``from evalglass.harness.cli import ...`` put ``evalglass.harness.cli`` in ``sys.modules``
    # before runpy could run it as ``__main__``, which made ``python -m evalglass.harness.cli``
    # emit a benign-but-noisy ``RuntimeWarning`` on every documented invocation (quickstart, run,
    # CI). Deferring it keeps ``from evalglass.harness import main`` working and drops the warning.
    if name in ("build_parser", "main"):
        from evalglass.harness import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DatasetConfig",
    "DatasetRead",
    "DatasetStore",
    "MarkdownScoreSink",
    "MetricConfig",
    "ResultPaths",
    "ResultStore",
    "RuntimeConfig",
    "ScoreSink",
    "SetupError",
    "TaskConfig",
    "TaskRequest",
    "TaskResult",
    "TaskRunner",
    "TerminalScoreSink",
    "TraceConfig",
    "TraceFormat",
    "TraceRead",
    "TraceSource",
    "TraceUnit",
    "build_parser",
    "example_from_trace",
    "load_config",
    "load_evaluator",
    "main",
    "setup_diagnostic",
]
