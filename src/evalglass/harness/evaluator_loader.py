"""Deterministic evaluator loading (EG-M1-4).

Resolves a metric's ``evaluator_ref`` to an effect-free ``Evaluator`` callable:

* a built-in by name (``exact_match``, ``set_overlap``, ``field_presence``,
  ``structural_shape``, ``judge_score``, ``trajectory_shape``; an ``@version`` suffix is allowed);
* a host-owned file as ``path.py:function`` (optionally ``file:`` prefixed), resolved
  relative to the run root.

Importing a host evaluator is the one place the harness executes host Python — it is
*explicit* (config-declared, no discovery) and *deterministic*, and every failure (unknown
ref, missing file, missing attribute, non-callable, import error) is a typed setup error.
The loaded evaluator receives only ``(Example, context, evidence)`` (CLAUDE.md §10).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

from evalglass.core import Evaluator
from evalglass.core.builtins import BUILTINS as _CORE_BUILTINS
from evalglass.harness.errors import SetupError, setup_diagnostic

# Derive the loader's registry from the single source of truth (``core.builtins.BUILTINS``) so a
# new built-in registered in the core is resolvable at runtime automatically — the two must never
# drift (each built-in has a single supported ``@N`` version). ``BUILTINS`` is keyed by the
# versioned ref (``numeric_bounds@1``); the loader resolves by base name + version.
_BUILTINS: dict[str, Evaluator] = {ref.partition("@")[0]: fn for ref, fn in _CORE_BUILTINS.items()}
#: The single supported version of each built-in (its ``@N`` suffix).
_BUILTIN_VERSION: dict[str, str] = {
    ref.partition("@")[0]: ref.partition("@")[2] for ref in _CORE_BUILTINS
}


def load_evaluator(ref: str, root: Path) -> Evaluator:
    """Resolve ``ref`` to an evaluator callable, or raise :class:`SetupError`."""
    if ref.startswith("file:") or ".py:" in ref:
        return _load_from_file(ref, root)
    base, sep, requested = ref.partition("@")
    evaluator = _BUILTINS.get(base)
    if evaluator is None:
        raise SetupError(
            setup_diagnostic(
                "evaluator_unknown",
                f"unknown evaluator_ref {ref!r}; built-ins: {sorted(_BUILTINS)} "
                "or a host file 'path.py:function'",
            )
        )
    # A requested version must match the one built-in we actually run — never silently
    # alias exact_match@99 to @1 while provenance records the wrong version.
    if sep and requested != _BUILTIN_VERSION[base]:
        raise SetupError(
            setup_diagnostic(
                "evaluator_unknown",
                f"unsupported version for built-in {base!r}: requested {requested!r}, "
                f"available {_BUILTIN_VERSION[base]!r}",
            )
        )
    return evaluator


def _load_from_file(ref: str, root: Path) -> Evaluator:
    spec_str = ref.removeprefix("file:")
    if ":" not in spec_str:
        raise SetupError(
            setup_diagnostic(
                "evaluator_unknown", f"evaluator_ref {ref!r} must be 'path.py:function'"
            )
        )
    path_part, _, func_name = spec_str.rpartition(":")
    file = root / path_part
    if not file.is_file():
        raise SetupError(
            setup_diagnostic(
                "evaluator_file_not_found", f"evaluator file not found: {file}", location=str(file)
            )
        )
    module = _import_file(file)
    func = getattr(module, func_name, None)
    if func is None:
        raise SetupError(
            setup_diagnostic(
                "evaluator_attr_missing",
                f"evaluator file {path_part} has no attribute {func_name!r}",
                location=str(file),
            )
        )
    if not callable(func):
        raise SetupError(
            setup_diagnostic(
                "evaluator_not_callable",
                f"evaluator {func_name!r} in {path_part} is not callable",
                location=str(file),
            )
        )
    return cast("Evaluator", func)


def _import_file(file: Path) -> ModuleType:
    mod_name = f"evalglass_host_eval__{file.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, file)
    if spec is None or spec.loader is None:
        raise SetupError(
            setup_diagnostic(
                "evaluator_import_failed",
                f"cannot load an evaluator module from {file}",
                location=str(file),
            )
        )
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module sees normal import semantics (e.g. host dataclasses
    # with postponed annotations that resolve via sys.modules[__name__]); roll back on failure.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # host code can raise anything on import — fail closed
        sys.modules.pop(mod_name, None)
        raise SetupError(
            setup_diagnostic(
                "evaluator_import_failed",
                f"failed importing evaluator {file}: {exc}",
                location=str(file),
            )
        ) from exc
    return module
