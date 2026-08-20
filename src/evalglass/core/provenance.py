"""Provenance fingerprints and baseline comparability (EG-M0-4b).

A score without provenance is uninterpretable; a regression without comparability
is not a claim (``CLAUDE.md §11``). A run is fingerprinted across structured
dimensions (framework, metric spec, evaluator, dataset, example, evidence,
config, policy, authority, baseline). A regression may be claimed only when the
current and baseline runs are *comparable* on the gating dimensions; otherwise
the state is explicit (non_comparable / missing_baseline / comparison_not_requested)
and no regression is manufactured. Stdlib-only (``hashlib``, ``json``).
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import ContractError, _opt_str_list, _require_mapping

#: The structured dimensions every run fingerprint must carry.
REQUIRED_DIMENSIONS: tuple[str, ...] = (
    "framework",
    "metric_spec",
    "evaluator",
    "dataset",
    "example",
    "evidence",
    "config",
    "policy",
    "authority",
    "baseline",
)

#: Dimensions that must match for two runs to support a regression claim.
#: ``example`` deliberately is not gating — different examples still compare.
DEFAULT_GATING_DIMENSIONS: tuple[str, ...] = (
    "framework",
    "metric_spec",
    "evaluator",
    "dataset",
    "config",
    "policy",
)


class BaselineState(enum.StrEnum):
    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not_comparable"
    MISSING_BASELINE = "missing_baseline"
    COMPARISON_NOT_REQUESTED = "comparison_not_requested"


def fingerprint_dimension(value: Any) -> str:
    """A deterministic, order-insensitive SHA-256 fingerprint of a JSON-able value.

    Fails closed on non-JSON values (e.g. a ``set``): hashing their ``repr`` would
    be order-/address-dependent and silently corrupt comparability.
    """
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise ContractError(f"provenance dimension is not JSON-serializable: {exc}") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunFingerprint:
    """Per-dimension fingerprints of a run; carries every required dimension."""

    dimensions: dict[str, str]

    @classmethod
    def of(cls, dimensions: Mapping[str, Any]) -> Self:
        missing = [dim for dim in REQUIRED_DIMENSIONS if dim not in dimensions]
        if missing:
            raise ContractError(
                f"RunFingerprint: missing required dimension(s): {', '.join(missing)}"
            )
        return cls(
            dimensions={dim: fingerprint_dimension(dimensions[dim]) for dim in REQUIRED_DIMENSIONS}
        )

    def to_dict(self) -> dict[str, Any]:
        return {"dimensions": dict(self.dimensions)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ContractError(f"RunFingerprint: expected a mapping, got {type(data).__name__}")
        dims = _require_mapping(data, "dimensions", "RunFingerprint")
        missing = [dim for dim in REQUIRED_DIMENSIONS if dim not in dims]
        if missing:
            raise ContractError(
                f"RunFingerprint: missing required dimension(s): {', '.join(missing)}"
            )
        if not all(isinstance(v, str) for v in dims.values()):
            raise ContractError("RunFingerprint: every dimension fingerprint must be a string")
        return cls(dimensions={str(k): str(v) for k, v in dims.items()})


@dataclass(frozen=True)
class ComparableRunFingerprint:
    """Whether a current run is comparable to a baseline for a regression claim."""

    current: RunFingerprint
    baseline: RunFingerprint | None = None
    requested: bool = False
    gating_dimensions: list[str] = field(default_factory=lambda: list(DEFAULT_GATING_DIMENSIONS))

    @property
    def changed_dimensions(self) -> list[str]:
        if self.baseline is None:
            return []
        changed: list[str] = []
        for dim in self.gating_dimensions:
            # A gating dimension absent from either side cannot be confirmed equal,
            # so it counts as changed — a misconfigured comparison fails closed
            # (non-comparable) rather than silently reporting comparable.
            if (
                dim not in self.current.dimensions
                or dim not in self.baseline.dimensions
                or self.current.dimensions[dim] != self.baseline.dimensions[dim]
            ):
                changed.append(dim)
        return changed

    @property
    def state(self) -> BaselineState:
        if not self.requested:
            return BaselineState.COMPARISON_NOT_REQUESTED
        if self.baseline is None:
            return BaselineState.MISSING_BASELINE
        if self.changed_dimensions:
            return BaselineState.NOT_COMPARABLE
        return BaselineState.COMPARABLE

    @property
    def can_support_regression(self) -> bool:
        """A regression claim is only honest when the runs are comparable."""
        return self.state is BaselineState.COMPARABLE

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "current": self.current.to_dict(),
            "requested": self.requested,
            "gating_dimensions": list(self.gating_dimensions),
            "state": self.state.value,
            "changed_dimensions": self.changed_dimensions,
        }
        if self.baseline is not None:
            out["baseline"] = self.baseline.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ComparableRunFingerprint: expected a mapping, got {type(data).__name__}"
            )
        # A present-but-malformed baseline must fail closed, not be read as "no baseline".
        baseline_obj: RunFingerprint | None = None
        if data.get("baseline") is not None:
            baseline_obj = RunFingerprint.from_dict(
                _require_mapping(data, "baseline", "ComparableRunFingerprint")
            )
        requested = data.get("requested", False)
        if not isinstance(requested, bool):
            raise ContractError("ComparableRunFingerprint: 'requested' must be a boolean")
        gating = data.get("gating_dimensions")
        gating_list = (
            _opt_str_list(data, "gating_dimensions", "ComparableRunFingerprint")
            if gating is not None
            else list(DEFAULT_GATING_DIMENSIONS)
        )
        return cls(
            current=RunFingerprint.from_dict(
                _require_mapping(data, "current", "ComparableRunFingerprint")
            ),
            baseline=baseline_obj,
            requested=requested,
            gating_dimensions=gating_list,
        )
