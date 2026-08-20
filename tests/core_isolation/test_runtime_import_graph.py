"""Executable (runtime) import-isolation for the Evaluation Core (M7 T0, G7).

The sibling ``test_core_imports.py`` proves core isolation *statically* — an AST
allowlist over each core source file. That is necessary but not sufficient: a
core module can be stdlib-clean in its own source yet, at import time, execute
code that pulls a forbidden effect/vendor module in *transitively*. Only the real
Python import graph can rule that out.

This test imports the Core in a **clean subprocess** and asserts that no Runtime
Harness / adapter / installer package and no third-party effect module (yaml,
requests, provider SDKs, …) ended up in ``sys.modules``. It also proves the leak
detector is sensitive — both against a synthetic dirty module set and against the
real Runtime Harness, which legitimately *does* load ``yaml``.

See ``docs/TETA_REDESIGN.md`` §2 (G7) and ``CLAUDE.md`` §4.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

# Third-party / effect modules whose presence after importing the Core is a leak.
_FORBIDDEN_TOP_LEVEL = frozenset(
    {
        "yaml",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "langfuse",
        "phoenix",
        "arize",
        "langsmith",
        "opentelemetry",
        "sentry_sdk",
        "pydantic",
    }
)
# Effectful internal packages that must never load transitively from the Core.
_FORBIDDEN_INTERNAL_PREFIXES = (
    "evalglass.harness",
    "evalglass.adapters",
    "evalglass.installer",
)


def _runtime_leaks(loaded: set[str]) -> list[str]:
    """Return the modules in ``loaded`` that violate Core runtime isolation."""
    leaks: list[str] = []
    for name in loaded:
        top = name.split(".", 1)[0]
        internal = any(name == p or name.startswith(p + ".") for p in _FORBIDDEN_INTERNAL_PREFIXES)
        if top in _FORBIDDEN_TOP_LEVEL or internal:
            leaks.append(name)
    return sorted(leaks)


def _modules_after_import(target: str) -> set[str]:
    """Import ``target`` in a fresh interpreter; return its ``sys.modules`` names."""
    code = f"import sys, json\nimport {target}\nsys.stdout.write(json.dumps(sorted(sys.modules)))\n"
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted interpreter
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return set(json.loads(proc.stdout))


# --- specificity: the real Core import graph is clean ----------------------


@pytest.mark.core_isolation
def test_importing_core_loads_no_runtime_or_vendor() -> None:
    loaded = _modules_after_import("evalglass.core")
    leaks = _runtime_leaks(loaded)
    assert leaks == [], (
        "Importing evalglass.core pulled effect/vendor modules into sys.modules: "
        f"{leaks}. The Core must be importable without the Runtime Harness or any "
        "third-party dependency (docs/TETA_REDESIGN.md G7, CLAUDE.md §4)."
    )
    # Sanity: we actually imported the Core (guards against a no-op green).
    assert any(m == "evalglass.core" or m.startswith("evalglass.core.") for m in loaded)


@pytest.mark.core_isolation
def test_importing_top_package_loads_no_runtime_or_vendor() -> None:
    # The top-level package __init__ must stay core-only (no eager runtime import).
    loaded = _modules_after_import("evalglass")
    assert _runtime_leaks(loaded) == []


# --- sensitivity: the detector fires on real and synthetic leaks -----------


@pytest.mark.core_isolation
def test_importing_harness_does_load_yaml() -> None:
    # The Runtime Harness legitimately loads yaml; this proves the subprocess
    # probe and detector would catch a Core that behaved like the Harness.
    loaded = _modules_after_import("evalglass.harness.config")
    assert "yaml" in loaded
    assert "yaml" in _runtime_leaks(loaded)


def test_leak_detector_reports_synthetic_leaks() -> None:
    dirty = {
        "evalglass.core",
        "evalglass.core.scores",
        "json",
        "yaml",
        "evalglass.harness.runner",
        "evalglass.adapters.judge_fake",
        "requests",
    }
    assert _runtime_leaks(dirty) == [
        "evalglass.adapters.judge_fake",
        "evalglass.harness.runner",
        "requests",
        "yaml",
    ]


def test_leak_detector_passes_a_clean_set() -> None:
    clean = {"evalglass", "evalglass.core", "evalglass.core.scores", "json", "hashlib", "math"}
    assert _runtime_leaks(clean) == []
