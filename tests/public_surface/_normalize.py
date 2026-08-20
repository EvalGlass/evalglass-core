"""Normalizers for the FS-SNAP public-surface freezes (EG-AT1-2).

The frozen public surfaces are introspected into deterministic, reviewable shapes
rather than compared as raw bytes: the CLI is reduced to its *parsed* verb/flag
surface (so an argparse rendering change across a Python bump cannot false-fail),
the Markdown report to its headline + section skeleton, and CI output to a
workflow-command count. The goldens these feed are byte-stable and human-auditable.
"""

from __future__ import annotations

import argparse
import enum
import importlib
import inspect
import pkgutil
import re
from typing import Any

#: Unearned-success words a report must never apply to a run subject. ``pass`` is
#: deliberately absent — ``pass/fail`` is legitimate verdict vocabulary; these are
#: the words that would *overclaim* correctness/safety.
OVERCLAIM_WORDS: frozenset[str] = frozenset(
    {
        "passing",
        "green",
        "safe",
        "verified",
        "certified",
        "certify",
        "trustworthy",
        "guaranteed",
        "proven",
    }
)

_WORD = re.compile(r"[a-z][a-z-]*")


def parser_surface(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Reduce an argparse parser to its parsed verb/flag surface (the primary contract).

    Returns ``{prog, description, options, commands}``. ``options`` maps each flag
    (its longest spelling) to ``{dest, flags, required, choices, default, help}`` and
    ``commands`` recurses into subparsers (each carrying its own ``help`` one-liner).
    The auto-added ``-h/--help`` action is excluded.

    The ``description`` and ``help`` *strings* (not argparse's rendered ``--help``
    text) are captured, so the surface freezes the user-visible help content — an
    overclaiming phrase drifts it — while staying independent of terminal width,
    which argparse's text wrapping depends on.
    """
    options: dict[str, Any] = {}
    commands: dict[str, Any] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            help_by_name = {sub.dest: sub.help for sub in action._get_subactions()}
            for name, sub in action.choices.items():
                surface = parser_surface(sub)
                surface["help"] = help_by_name.get(name)
                commands[name] = surface
        elif action.option_strings and action.dest != "help":
            flag = max(action.option_strings, key=len)
            default = action.default
            options[flag] = {
                "dest": action.dest,
                # Record *every* spelling, so adding/removing a short alias (e.g. -c)
                # to an existing flag drifts the frozen surface, not just a new flag.
                "flags": sorted(action.option_strings),
                "required": bool(action.required),
                "choices": sorted(action.choices) if action.choices else None,
                "default": None if default is argparse.SUPPRESS else default,
                "help": action.help,
            }
    return {
        "prog": parser.prog,
        "description": parser.description,
        "options": options,
        "commands": commands,
    }


def help_prose(surface: dict[str, Any]) -> str:
    """All user-visible help/description prose in a :func:`parser_surface`, joined.

    Used to assert no overclaim word leaks into ``evalglass --help`` — independent of
    rendering width, since it reads the raw strings the surface already froze.
    """
    parts = [surface.get("description") or "", surface.get("help") or ""]
    for option in surface.get("options", {}).values():
        parts.append(option.get("help") or "")
    for command in surface.get("commands", {}).values():
        parts.append(help_prose(command))
    return " ".join(p for p in parts if p)


def report_structure(markdown: str) -> dict[str, Any]:
    """Extract the report's stable skeleton: headline, verdict/CI lines, section order."""
    lines = markdown.split("\n")
    return {
        "headline": lines[0] if lines else "",
        "has_verdict_line": any(line.startswith("**Verdict:**") for line in lines),
        "has_ci_line": any(line.startswith("**CI:**") for line in lines),
        "sections": [line for line in lines if line.startswith("## ")],
    }


def report_verdict_words(markdown: str) -> list[str]:
    """Every word claimed by a ``**Verdict:**`` line, in order.

    Returns a *list* (not the first match) so an appended second verdict
    headline — a report that keeps the honest line but later overclaims — is
    visible to the caller, which can require exactly one line equal to the
    Scorecard verdict.
    """
    words: list[str] = []
    for line in markdown.split("\n"):
        if line.startswith("**Verdict:**"):
            rest = line[len("**Verdict:**") :].strip()
            if rest:
                words.append(rest.split()[0])
    return words


def report_overclaim_words(markdown: str) -> set[str]:
    """The set of :data:`OVERCLAIM_WORDS` present as whole words in the report."""
    tokens = set(_WORD.findall(markdown.lower()))
    return tokens & OVERCLAIM_WORDS


def ci_command_count(text: str) -> int:
    """Number of GitHub workflow commands (lines beginning ``::``) in CI output."""
    return sum(1 for line in text.splitlines() if line.startswith("::"))


#: The runtime packages whose every ``Enum`` is part of the frozen public contract.
_ENUM_PACKAGES = ("evalglass.core", "evalglass.harness")


def enum_members(enum_cls: type[enum.Enum]) -> list[list[str]]:
    """An enum's members as ordered ``[name, value]`` pairs.

    Both halves are frozen: the *value* is the serialized contract, the *name* is the
    Python API (``Verdict.PASS`` is imported by code), and the order is preserved so a
    rename, a value change, or a reorder all drift the snapshot. Iterates
    ``__members__`` (not the enum directly) so **aliases** — extra public names like
    ``ALSO_PASS = "pass"`` — are frozen too, not silently omitted.
    """
    return [[name, str(member.value)] for name, member in enum_cls.__members__.items()]


def discover_runtime_enums() -> dict[str, list[list[str]]]:
    """Map ``module.Qualname`` -> ``[name, value]`` pairs for every Enum in the runtime.

    Walks ``evalglass.core`` and ``evalglass.harness`` so a *newly added* enum
    auto-appears here and must be frozen in the golden — a hand-maintained list would
    silently miss it (the no-false-confidence rule applied to the enum freeze).
    Re-exports are excluded by checking ``obj.__module__``.
    """
    found: dict[str, list[list[str]]] = {}
    for package_name in _ENUM_PACKAGES:
        package = importlib.import_module(package_name)
        for _, modname, _ in pkgutil.walk_packages(package.__path__, package_name + "."):
            module = importlib.import_module(modname)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, enum.Enum) and obj.__module__ == modname:
                    found[f"{modname}.{obj.__qualname__}"] = enum_members(obj)
    return found


def is_sort_key_stable(json_text: str) -> bool:
    """True iff a JSON document is already serialized canonically (``sort_keys`` + 2-indent)."""
    import json

    return json.dumps(json.loads(json_text), indent=2, sort_keys=True) + "\n" == json_text
