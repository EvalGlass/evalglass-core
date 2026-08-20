"""Generated-evidence governance (EG-M5-6; ADR 0021).

Annotation outputs, synthetic datasets, and benchmark results are *useful but unvalidated* inputs.
This module keeps them honest so they cannot manufacture authority (build contract §2/§10/§12):

- **Synthetic data stays `proposed`** until a host validates it — a generated dataset can never
  self-validate; a hopeful ``declared_status`` is made safe, never honored.
- **An annotation is an authority input only with a host validation record** — without one it is
  informational evidence, never gating input.
- **A benchmark provides threshold *evidence* but can never approve a threshold** — only a host
  ``ApprovedThreshold`` record (with a real approver) can, via the M4 calibration path.

Nothing here fabricates authority: validation/approval live in the host's ``AuthorityRecord`` (M3)
and ``ApprovedThreshold`` (M4); this module only refuses to let generated artifacts bypass them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evalglass.core import DatasetStatus
from evalglass.harness.calibration import ApprovedThreshold


class GovernanceError(ValueError):
    """Raised when a generated artifact attempts to bypass host validation/approval."""


@dataclass(frozen=True)
class AnnotationImport:
    """A host-imported annotation output — an authority input only with a validation record."""

    annotation_id: str
    value: Any
    validation_record: str | None = None

    @property
    def is_authority_input(self) -> bool:
        """True only when a host validation record backs the annotation; else informational.

        The record is typed ``str | None``; the explicit ``isinstance`` guard makes a
        non-string record (a hopeful caller bypassing the type) *not-authority* rather
        than crashing or silently coercing it into a truthy value.
        """
        return isinstance(self.validation_record, str) and bool(self.validation_record.strip())

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"annotation_id": self.annotation_id, "value": self.value}
        if self.validation_record:
            out["validation_record"] = self.validation_record
        return out


@dataclass(frozen=True)
class SyntheticDataset:
    """A generated dataset. Its status is **always** ``proposed`` until a host validates it."""

    name: str
    example_count: int

    @property
    def status(self) -> DatasetStatus:
        return DatasetStatus.PROPOSED


@dataclass(frozen=True)
class BenchmarkEvidence:
    """A benchmark result that can *support* a threshold but can never *approve* one."""

    metric: str
    observed: float
    runs: int

    def supports(self, threshold: ApprovedThreshold) -> bool:
        """Whether the observed value clears an **already-approved** threshold (informational)."""
        if threshold.direction.value == "higher_is_better":
            return self.observed >= threshold.value
        return self.observed <= threshold.value


def import_synthetic_dataset(
    name: str, example_count: int, *, declared_status: str = "validated"
) -> SyntheticDataset:
    """Import a generated dataset — its status is forced to ``proposed`` regardless of any claim.

    ``declared_status`` is accepted but never honored: synthetic data starts proposed until a host
    validation record exists. The hopeful claim is made safe, not trusted.
    """
    del declared_status  # synthetic data can never self-validate
    return SyntheticDataset(name=name, example_count=example_count)


def approve_threshold_from_benchmark(evidence: BenchmarkEvidence) -> ApprovedThreshold:
    """Refuse: a benchmark cannot approve a threshold — a host ``ApprovedThreshold`` is required.

    Benchmarking can provide *evidence* (:meth:`BenchmarkEvidence.supports`) toward a threshold a
    host later approves, but it can never bypass the human approver the calibration path requires.
    """
    raise GovernanceError(
        f"benchmark evidence for {evidence.metric!r} cannot approve a threshold; a host "
        "ApprovedThreshold record (with an approver, rationale, and variance) is required"
    )
