"""Adapters — concrete implementations of ports owned by the Runtime Harness.

Vendor SDK imports belong here, never in :mod:`evalglass.core`.
"""

from __future__ import annotations

from evalglass.adapters.ci_annotation_sink import CiAnnotationSink
from evalglass.adapters.dataset_jsonl import LocalJsonlDatasetStore
from evalglass.adapters.result_store_fs import FilesystemResultStore
from evalglass.adapters.task_subprocess import SubprocessTaskRunner
from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
from evalglass.adapters.trace_open_convention import OpenConventionTraceSource

__all__ = [
    "CiAnnotationSink",
    "FilesystemResultStore",
    "LocalJsonlDatasetStore",
    "LocalJsonlTraceSource",
    "OpenConventionTraceSource",
    "SubprocessTaskRunner",
]
