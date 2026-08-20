"""FS-ISO — v2 import-boundary + maturity-is-never-a-verdict guards (EG-AT1 Slice 5, EG-AT1-5).

Extends core isolation for the v2 surface:

* **FS-ISO-1** — the Evaluation Core imports only its frozen stdlib allowlist +
  ``evalglass.core.*`` (an allowlist, complementing the existing forbidden-import scan).
* **FS-ISO-2** — ``runner.py`` has no *module-level* import of any optional lane; lanes
  stay lazy (a function-level import is fine).
* **FS-ISO-3** — ``core/verdict.py``, ``core/authority.py``, and ``harness/exits.py``
  never reference a ``maturity`` symbol or a capability-status literal — capability
  status is never a gate input.
* **FS-ISO-4** — no provider/observability SDK is imported anywhere on the required
  import closure (core + harness + non-lane adapters); SDKs live only in lazily-resolved
  lane modules.

Each detector is proven by a synthesized sensitivity fixture (it fires on bad code) and
by the real tree scanning clean (specificity).
"""

from __future__ import annotations

import ast
from pathlib import Path

from evalglass.harness.lanes import built_in_lanes

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"

#: Top-level stdlib modules the effect-free core may import (CLAUDE.md §8), frozen.
_CORE_STDLIB_ALLOWLIST = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "decimal",
        "enum",
        "hashlib",
        "json",
        "math",
        "statistics",  # M7 T1: pure stdlib math (NormalDist, fmean, stdev) for interval estimators
        "typing",
    }
)

#: The three files where a capability-status / maturity input would be a category error.
_NO_MATURITY_FILES = (
    _SRC / "core" / "verdict.py",
    _SRC / "core" / "authority.py",
    _SRC / "harness" / "exits.py",
)

_CAPABILITY_LITERALS = frozenset({"now", "next", "planned", "experimental"})

#: Provider / observability SDK top-level names that must never reach a required path.
_PROVIDER_SDKS = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "mistralai",
        "litellm",
        "vertexai",
        "ollama",
        "langfuse",
        "phoenix",
        "arize",
        "langsmith",
        "langchain",
        "llama_index",
        "transformers",
        "huggingface_hub",
        "boto3",
        "deepeval",
        "ragas",
        "promptfoo",
        "garak",
        "mlflow",
        "langgraph",
        "temporal",
        "opentelemetry",
        "openinference",
        "sentry_sdk",
    }
)


def _import_from_targets(node: ast.ImportFrom) -> set[str]:
    """The module + each ``module.name`` for a ``from module import name`` (level-0 only).

    Recording ``module.name`` too catches package-form submodule imports such as
    ``from evalglass.adapters import score_sink_export`` (which imports the lane module
    ``evalglass.adapters.score_sink_export``, not just the package).
    """
    if not node.module or node.level != 0:
        return set()
    return {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}


def _imported_modules(source: str) -> set[str]:
    """Every module imported anywhere in ``source`` (absolute imports only)."""
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods |= _import_from_targets(node)
    return mods


class _ModuleLevelImports(ast.NodeVisitor):
    """Collect imports that execute at module load — never descending into function bodies."""

    def __init__(self) -> None:
        self.modules: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # lazy, function-local imports are fine

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Import(self, node: ast.Import) -> None:
        self.modules.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.modules |= _import_from_targets(node)


def _module_level_imports(source: str) -> set[str]:
    visitor = _ModuleLevelImports()
    visitor.visit(ast.parse(source))
    return visitor.modules


def _references_symbol(source: str, symbol: str) -> bool:
    """True if ``symbol`` appears as a name or attribute anywhere in ``source``."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == symbol:
            return True
        if isinstance(node, ast.Attribute) and node.attr == symbol:
            return True
    return False


def _core_import_allowed(module: str) -> bool:
    return module.startswith("evalglass.core") or module.split(".")[0] in _CORE_STDLIB_ALLOWLIST


def _lane_module_files() -> set[Path]:
    return {
        (_SRC.parent / (lane.module.replace(".", "/") + ".py")).resolve()
        for lane in built_in_lanes().lanes()
    }


def _required_python_files() -> list[Path]:
    """core + harness + non-lane adapters — the closure that must stay SDK/lane-free."""
    lane_files = _lane_module_files()
    files: list[Path] = []
    for package in ("core", "harness", "adapters"):
        for path in (_SRC / package).rglob("*.py"):
            if path.resolve() not in lane_files:
                files.append(path)
    return files


# --------------------------------------------------------------------------- #
# FS-ISO-1 — core import allowlist
# --------------------------------------------------------------------------- #


def test_core_import_set_within_allowlist() -> None:
    offenders: list[str] = []
    for path in sorted((_SRC / "core").rglob("*.py")):
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            if not _core_import_allowed(module):
                offenders.append(f"{path.relative_to(_SRC)} imports {module}")
    assert not offenders, f"core imports outside the allowlist (harness/adapters/SDK?): {offenders}"


def test_sensitivity_core_importing_harness_is_flagged() -> None:
    assert not _core_import_allowed("evalglass.harness")  # a harness import would fail FS-ISO-1
    assert _core_import_allowed("evalglass.core.verdict")  # specificity: real core import is fine
    assert _core_import_allowed("collections.abc")


# --------------------------------------------------------------------------- #
# FS-ISO-2 — runner has no module-level lane import
# --------------------------------------------------------------------------- #


def test_runner_has_no_module_level_lane_import() -> None:
    runner = _SRC / "harness" / "runner.py"
    lane_modules = {lane.module for lane in built_in_lanes().lanes()}
    module_imports = _module_level_imports(runner.read_text(encoding="utf-8"))
    leaked = sorted(lane_modules & module_imports)
    assert not leaked, (
        f"runner.py imports an optional lane at module level (un-lazying it): {leaked}"
    )


def test_sensitivity_module_level_lane_import_detected() -> None:
    bad = "from evalglass.adapters.score_sink_export import FileScorecardExportSink\n"
    assert "evalglass.adapters.score_sink_export" in _module_level_imports(bad)
    # package form: `from evalglass.adapters import score_sink_export` imports the lane
    # submodule, not just the package — it must still be caught.
    package_form = "from evalglass.adapters import score_sink_export\n"
    assert "evalglass.adapters.score_sink_export" in _module_level_imports(package_form)
    # specificity: a function-local (lazy) import is NOT a module-level import.
    lazy = "def f():\n    from evalglass.adapters.score_sink_export import X\n    return X\n"
    assert "evalglass.adapters.score_sink_export" not in _module_level_imports(lazy)


# --------------------------------------------------------------------------- #
# FS-ISO-3 — maturity / capability status is never a verdict input
# --------------------------------------------------------------------------- #


def test_maturity_symbol_never_in_verdict_exits_authority() -> None:
    for path in _NO_MATURITY_FILES:
        source = path.read_text(encoding="utf-8")
        assert not _references_symbol(source, "maturity"), f"{path.name} references 'maturity'"
        literals = {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        leaked = literals & _CAPABILITY_LITERALS
        assert not leaked, f"{path.name} uses a capability-status literal as a value: {leaked}"


def test_sensitivity_verdict_branching_on_maturity_is_flagged() -> None:
    bad = (
        "def decide(lane):\n"
        "    if lane.maturity == 'now':\n"
        "        return 'pass'\n"
        "    return 'informational'\n"
    )
    assert _references_symbol(bad, "maturity")


# --------------------------------------------------------------------------- #
# FS-ISO-4 — no provider SDK on the required closure
# --------------------------------------------------------------------------- #


def test_no_provider_sdk_in_required_closure() -> None:
    offenders: list[str] = []
    for path in _required_python_files():
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            if module.split(".")[0] in _PROVIDER_SDKS:
                offenders.append(f"{path.relative_to(_SRC)} imports provider SDK {module}")
    assert not offenders, f"a provider SDK reached the required import closure: {offenders}"


def test_sensitivity_provider_sdk_import_detected() -> None:
    bad = "import langfuse\nfrom openai import OpenAI\n"
    imported = _imported_modules(bad)
    assert any(module.split(".")[0] in _PROVIDER_SDKS for module in imported)
    # specificity: the real required closure scans clean (no provider SDK).
    clean = _imported_modules("import json\nfrom evalglass.core import Scorecard\n")
    assert not any(module.split(".")[0] in _PROVIDER_SDKS for module in clean)
