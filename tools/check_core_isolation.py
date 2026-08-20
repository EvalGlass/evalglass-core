#!/usr/bin/env python3
"""Structural enforcement of Evaluation Core isolation (CLAUDE.md §4).

This is NOT a stylistic linter — it is a measurement-integrity gate. The
Evaluation Core is the only place in EvalGlass whose verdicts are allowed to
carry authority. If the core can read files, call LLMs, look at the clock, or
import vendor SDKs, then its outputs cannot be trusted as deterministic
functions of their inputs, and the trust model collapses.

Usage
-----
    python tools/check_core_isolation.py [PATH ...]

If no paths are given, defaults to ``src/evalglass/core``.

Exits non-zero on any violation, printing a structured diagnostic with file,
line, kind, and the offending name.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# Forbidden surface
# --------------------------------------------------------------------------- #

# Top-level module names that may not be imported from the Evaluation Core.
# Grouped by category so the diagnostic message is informative.
FORBIDDEN_MODULE_PREFIXES: dict[str, str] = {
    # File I/O
    "os": "filesystem / process state",
    "pathlib": "filesystem",
    "io": "I/O",
    "shutil": "filesystem",
    "tempfile": "filesystem",
    "fileinput": "filesystem",
    "glob": "filesystem",
    "fnmatch": "filesystem",
    # Process / OS
    "subprocess": "subprocess",
    "multiprocessing": "subprocess",
    "signal": "process signals",
    "resource": "process state",
    "platform": "host environment",
    # Network
    "socket": "network",
    "ssl": "network",
    "select": "network",
    "selectors": "network",
    "asyncio": "asynchronous I/O",
    "urllib": "network",
    "urllib3": "network",
    "http": "network",
    "requests": "network (vendor)",
    "httpx": "network (vendor)",
    "aiohttp": "network (vendor)",
    "websockets": "network (vendor)",
    # Time / non-determinism
    "time": "wall-clock time",
    "datetime": "wall-clock time",
    "sched": "wall-clock time",
    "random": "non-determinism",
    "secrets": "non-determinism",
    "uuid": "non-determinism",
    # Persistence / data stores
    "sqlite3": "database",
    "shelve": "persistence",
    "dbm": "persistence",
    "pickle": "untrusted persistence",
    # Environment
    "dotenv": "environment",
    "environs": "environment",
    # Telemetry / phone-home (CLAUDE.md §2)
    "opentelemetry": "telemetry",
    "sentry_sdk": "telemetry",
    # LLM / vendor SDKs (CLAUDE.md §4)
    "openai": "LLM vendor SDK",
    "anthropic": "LLM vendor SDK",
    "google": "vendor SDK",
    "vertexai": "LLM vendor SDK",
    "cohere": "LLM vendor SDK",
    "mistralai": "LLM vendor SDK",
    "langchain": "LLM framework",
    "llama_index": "LLM framework",
    "llamaindex": "LLM framework",
    "boto3": "vendor SDK (AWS)",
    "botocore": "vendor SDK (AWS)",
}

# ``sys`` is partially allowed: ``sys.version_info`` is fine, but ``sys.argv``,
# ``sys.stdin/stdout/stderr``, ``sys.exit``, etc. are I/O / process state.
# We treat any ``sys.<attr>`` access where attr is in this set as forbidden.
FORBIDDEN_SYS_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "argv",
        "stdin",
        "stdout",
        "stderr",
        "exit",
        "exc_info",
        "settrace",
        "setprofile",
        "modules",
        "path",
        "executable",
    }
)

# Builtin call names that imply I/O or non-determinism even without an import.
FORBIDDEN_BUILTIN_CALLS: frozenset[str] = frozenset({"open", "input", "print", "exec", "eval"})


# --------------------------------------------------------------------------- #
# Diagnostic model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Violation:
    """A single core-isolation violation."""

    file: Path
    line: int
    column: int
    kind: str  # "import" | "from-import" | "sys-attribute" | "builtin-call"
    name: str
    category: str

    def render(self, repo_root: Path) -> str:
        try:
            rel = self.file.relative_to(repo_root)
        except ValueError:
            rel = self.file
        return f"{rel}:{self.line}:{self.column}: [{self.kind}] {self.name!r} ({self.category})"


# --------------------------------------------------------------------------- #
# AST visitor
# --------------------------------------------------------------------------- #


class CoreIsolationVisitor(ast.NodeVisitor):
    """Walk a single Python module's AST and collect violations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[Violation] = []

    # ----- imports --------------------------------------------------------- #

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            category = _forbidden_module_category(alias.name)
            if category is not None:
                self.violations.append(
                    Violation(
                        file=self.path,
                        line=node.lineno,
                        column=node.col_offset,
                        kind="import",
                        name=alias.name,
                        category=category,
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            # Relative imports — fine; they stay inside the core package.
            self.generic_visit(node)
            return
        category = _forbidden_module_category(node.module)
        if category is not None:
            for alias in node.names:
                self.violations.append(
                    Violation(
                        file=self.path,
                        line=node.lineno,
                        column=node.col_offset,
                        kind="from-import",
                        name=f"{node.module}.{alias.name}",
                        category=category,
                    )
                )
        self.generic_visit(node)

    # ----- sys.<forbidden-attr> ------------------------------------------- #

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr in FORBIDDEN_SYS_ATTRIBUTES
        ):
            self.violations.append(
                Violation(
                    file=self.path,
                    line=node.lineno,
                    column=node.col_offset,
                    kind="sys-attribute",
                    name=f"sys.{node.attr}",
                    category="process state / I/O",
                )
            )
        self.generic_visit(node)

    # ----- builtin calls --------------------------------------------------- #

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTIN_CALLS:
            self.violations.append(
                Violation(
                    file=self.path,
                    line=node.lineno,
                    column=node.col_offset,
                    kind="builtin-call",
                    name=node.func.id,
                    category="I/O / dynamic execution",
                )
            )
        self.generic_visit(node)


def _forbidden_module_category(module: str) -> str | None:
    """Return the forbidden-category label for *module*, or None if allowed."""
    top = module.split(".", 1)[0]
    return FORBIDDEN_MODULE_PREFIXES.get(top)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every ``*.py`` file under *root* (sorted, stable)."""
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    yield from sorted(root.rglob("*.py"))


def scan(paths: Iterable[Path]) -> list[Violation]:
    """Scan one or more roots and return all violations found."""
    violations: list[Violation] = []
    for root in paths:
        for file in iter_python_files(root):
            try:
                source = file.read_text(encoding="utf-8")
            except OSError as exc:  # pragma: no cover — IO error reading own source
                print(f"warning: could not read {file}: {exc}", file=sys.stderr)
                continue
            tree = ast.parse(source, filename=str(file))
            visitor = CoreIsolationVisitor(file)
            visitor.visit(tree)
            violations.extend(visitor.violations)
    return violations


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if len(argv) > 1:
        roots = [Path(p).resolve() for p in argv[1:]]
    else:
        roots = [repo_root / "src" / "evalglass" / "core"]

    for root in roots:
        if not root.exists():
            print(f"error: path does not exist: {root}", file=sys.stderr)
            return 2

    violations = scan(roots)
    if not violations:
        print(f"core-isolation: OK — scanned {len(roots)} root(s), 0 violations.")
        return 0

    print(f"core-isolation: FAIL — {len(violations)} violation(s):", file=sys.stderr)
    for v in violations:
        print(f"  {v.render(repo_root)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
