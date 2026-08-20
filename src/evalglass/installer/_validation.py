"""Fail-closed parse helpers for skill contracts (EG-M3-1).

The skill is its own layer; rather than reach into the core's private
``_validation`` helpers it carries a small, self-contained set that mirrors the
same discipline — a missing or wrong-typed field raises :class:`InstallerError`, never
a silent coercion (M0 lesson: parsing is the #1 bug class). Stdlib-only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class InstallerError(ValueError):
    """Raised when a skill artifact is malformed or a contract is violated."""


def _as_mapping(data: Any, ctx: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise InstallerError(f"{ctx}: expected a mapping, got {type(data).__name__}")
    return data


def _require(m: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in m:
        raise InstallerError(f"{ctx}: missing required field {key!r}")
    return m[key]


def _require_str(m: Mapping[str, Any], key: str, ctx: str) -> str:
    value = _require(m, key, ctx)
    if not isinstance(value, str) or not value:
        raise InstallerError(f"{ctx}: field {key!r} must be a non-empty string, got {value!r}")
    return value


def _require_bool(m: Mapping[str, Any], key: str, ctx: str) -> bool:
    value = _require(m, key, ctx)
    if not isinstance(value, bool):
        raise InstallerError(f"{ctx}: field {key!r} must be a boolean, got {value!r}")
    return value


def _str_list(m: Mapping[str, Any], key: str, ctx: str, *, required: bool = False) -> list[str]:
    if key not in m:
        if required:
            raise InstallerError(f"{ctx}: missing required field {key!r}")
        return []
    value = m[key]
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise InstallerError(f"{ctx}: field {key!r} must be a list of non-empty strings")
    return list(value)


def _mapping_list(m: Mapping[str, Any], key: str, ctx: str) -> list[Mapping[str, Any]]:
    if key not in m:
        return []
    value = m[key]
    if not isinstance(value, list):
        raise InstallerError(f"{ctx}: field {key!r} must be a list")
    out: list[Mapping[str, Any]] = []
    for item in value:
        out.append(_as_mapping(item, f"{ctx}.{key}[]"))
    return out
