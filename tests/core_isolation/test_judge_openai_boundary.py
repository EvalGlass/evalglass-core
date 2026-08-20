"""Import-boundary guard: the OpenAI-compatible judge is imported only lazily (ADR 0052).

The OpenAI-compatible judge is a first-class, config-selectable measurement adapter
(``judge.adapter: openai_compatible``), like the host command judge. To keep the required tier
hermetic and the adapter deletable, no required module — ``core``, ``harness``, or any *other*
adapter — may import ``adapters/judge_openai.py`` **at module load time**: the sole importer
resolves it *lazily*, inside a function, only when an ``openai_compatible`` judge is configured. So
importing the runtime imports no provider transport, a fake/no-judge run never pulls the adapter in,
and deleting the file leaves the required (fake) judge suite green. Fast, deterministic AST check.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"
_ADAPTER = "evalglass.adapters.judge_openai"
_REQUIRED_PKGS = ("core", "harness", "adapters")


def _module_level_nodes(module: ast.Module) -> Iterator[ast.AST]:
    """Yield nodes that execute at import time — i.e. everything except function bodies.

    Class bodies and module-level ``if``/``try``/``with`` run at import; only statements inside a
    (sync or async) function are lazy. Recurse through the former, stop at the latter.
    """

    def walk(nodes: list[ast.stmt]) -> Iterator[ast.AST]:
        for node in nodes:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue  # a function body runs only when called — a lazy import lives here
            yield node
            yield from walk([c for c in ast.iter_child_nodes(node) if isinstance(c, ast.stmt)])

    yield from walk(module.body)


def _imports_adapter_at_module_load(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in _module_level_nodes(tree):
        if isinstance(node, ast.Import) and any(a.name == _ADAPTER for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "") == _ADAPTER:
            return True
    return False


def test_required_tier_does_not_import_the_openai_judge_adapter_at_module_load() -> None:
    adapter_file = _SRC / "adapters" / "judge_openai.py"
    offenders: list[str] = []
    for pkg in _REQUIRED_PKGS:
        for py in (_SRC / pkg).rglob("*.py"):
            if py != adapter_file and _imports_adapter_at_module_load(py):
                offenders.append(str(py.relative_to(_SRC)))
    assert not offenders, (
        "required modules import the OpenAI judge adapter at module load "
        f"(it must be imported lazily inside a function): {offenders}"
    )


def test_the_openai_adapter_is_reachable_only_through_a_lazy_import() -> None:
    """The promotion is real: runner.py *does* import the adapter, but only lazily (in a function).

    Sensitivity guard for the check above — if the lazy import were hoisted to module scope, the
    module-load scan would catch it; here we prove the function-local import exists at all, so the
    ``openai_compatible`` route is wired rather than silently dead.
    """
    runner = _SRC / "harness" / "runner.py"
    tree = ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    lazy = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "") == _ADAPTER
    ]
    assert lazy, "runner.py no longer imports the OpenAI judge adapter — the route is dead"
    assert not _imports_adapter_at_module_load(runner), "the adapter import must stay lazy"
