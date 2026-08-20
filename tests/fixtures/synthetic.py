"""F-4 — synthetic-generator stub (EG-AT0-4).

Deterministic generation *request* whose only purpose is to prove the governance
funnel: routed through ``import_synthetic_dataset`` the result is **always**
``proposed`` and any ``declared_status`` is dropped. No live model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evalglass.harness.governance import SyntheticDataset, import_synthetic_dataset


@dataclass(frozen=True)
class SyntheticRequest:
    """A deterministic generation request (fixed examples; no model)."""

    name: str
    examples: tuple[dict[str, Any], ...]
    declared_status: str = "proposed"

    def imported(self) -> SyntheticDataset:
        """Route through the real governance funnel (status forced to proposed)."""
        return import_synthetic_dataset(
            self.name, len(self.examples), declared_status=self.declared_status
        )


def _deterministic_examples(n: int, seed: int) -> tuple[dict[str, Any], ...]:
    if n < 0:
        raise ValueError(f"synthetic request size must be non-negative, got {n}")
    return tuple({"input": f"q{seed}-{i}", "output": f"a{seed}-{i}"} for i in range(n))


def make_synthetic_request(*, n: int = 3, seed: int = 0) -> SyntheticRequest:
    """A clean (specificity) synthetic request — honestly declared proposed."""
    return SyntheticRequest(name="synthetic", examples=_deterministic_examples(n, seed))


def make_synthetic_request_claiming_validated(*, n: int = 3, seed: int = 0) -> SyntheticRequest:
    """A sensitivity request that *claims* ``validated`` — the funnel must strip it."""
    return SyntheticRequest(
        name="synthetic-claims-validated",
        examples=_deterministic_examples(n, seed),
        declared_status="validated",
    )


__all__ = [
    "SyntheticRequest",
    "make_synthetic_request",
    "make_synthetic_request_claiming_validated",
]
