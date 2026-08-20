"""Shared fail-closed parsing helpers for the effect-free Evaluation Core.

Every public contract parses external payloads with these helpers so the whole
core fails closed identically: a missing or malformed field raises
:class:`ContractError` rather than being silently coerced. Stdlib-only
(``CLAUDE.md §8``); imported by ``contracts.py``, ``scores.py``, and the
measurement/output contract modules that follow.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping
from typing import Any


class ContractError(ValueError):
    """Raised when a payload cannot be parsed into a valid public contract."""


def _as_mapping(data: object, ctx: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ContractError(f"{ctx}: expected a mapping, got {type(data).__name__}")
    return data


def _require(data: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in data:
        raise ContractError(f"{ctx}: missing required field '{key}'")
    return data[key]


def _require_str(data: Mapping[str, Any], key: str, ctx: str) -> str:
    value = _require(data, key, ctx)
    if not isinstance(value, str) or not value:
        raise ContractError(f"{ctx}: field '{key}' must be a non-empty string, got {value!r}")
    return value


def _require_mapping(data: Mapping[str, Any], key: str, ctx: str) -> dict[str, Any]:
    value = _require(data, key, ctx)
    if not isinstance(value, Mapping):
        raise ContractError(f"{ctx}: field '{key}' must be a mapping, got {type(value).__name__}")
    return dict(value)


def _coerce_enum[E: enum.Enum](cls: type[E], value: Any, key: str, ctx: str) -> E:
    try:
        return cls(value)
    except ValueError:
        allowed = ", ".join(str(member.value) for member in cls)
        raise ContractError(
            f"{ctx}: field '{key}' has unknown value {value!r}; expected one of: {allowed}"
        ) from None


def _opt_str(data: Mapping[str, Any], key: str, ctx: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractError(f"{ctx}: field '{key}' must be a string when present")
    return value


def _opt_mapping(data: Mapping[str, Any], key: str, ctx: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        raise ContractError(f"{ctx}: field '{key}' must be a mapping when present")
    return dict(value)


def _opt_list(data: Mapping[str, Any], key: str, ctx: str) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ContractError(f"{ctx}: field '{key}' must be a list when present")
    return list(value)


def _opt_str_list(data: Mapping[str, Any], key: str, ctx: str) -> list[str]:
    value = _opt_list(data, key, ctx)
    if not all(isinstance(item, str) for item in value):
        raise ContractError(f"{ctx}: field '{key}' must be a list of strings")
    return value


def _as_finite_float(value: object, key: str, ctx: str) -> float:
    """Validate a single value as a finite real number (rejecting bool / overflow)."""
    # bool is an int subclass but is never a meaningful numeric measurement.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ContractError(f"{ctx}: field '{key}' must be a number when present, got {value!r}")
    try:
        number = float(value)
    except OverflowError:
        # An external JSON integer too large to become a float must fail *closed*.
        raise ContractError(
            f"{ctx}: field '{key}' is too large to represent as a float, got {value!r}"
        ) from None
    if not math.isfinite(number):
        raise ContractError(f"{ctx}: field '{key}' must be finite (no NaN/inf), got {value!r}")
    return number


def _as_int(value: object, key: str, ctx: str) -> int:
    """Validate a single value as an integer (rejecting bool)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{ctx}: field '{key}' must be an integer when present, got {value!r}")
    return value


def _opt_float(data: Mapping[str, Any], key: str, ctx: str) -> float | None:
    value = data.get(key)
    return None if value is None else _as_finite_float(value, key, ctx)


def _opt_int(data: Mapping[str, Any], key: str, ctx: str) -> int | None:
    value = data.get(key)
    return None if value is None else _as_int(value, key, ctx)
