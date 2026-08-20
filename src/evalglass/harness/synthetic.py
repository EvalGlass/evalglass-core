"""Synthetic dataset generator (EG-H3-1; ADR 0021; alignment plan §5.4, delta D5).

A real, stdlib-only *local* capability that deterministically expands host-provided seed examples
into a generated dataset on disk and routes it through the proposed-forcing governance funnel
(:func:`~evalglass.harness.governance.import_synthetic_dataset`). It lives in the harness, never the
Core, and it manufactures **no authority**:

- **Generated data stays ``proposed``.** A generated dataset is always
  :attr:`~evalglass.core.authority.DatasetStatus.PROPOSED`; synthetic-origin data can never resolve
  ``can_gate=true`` (proven in ``tests/harness/test_synthetic_generator.py``). Host validation is a
  separate, host-owned action that creates a distinct non-synthetic dataset or authority record.
- **Local + reviewable.** It writes ``evals/datasets/generated/<name>.jsonl`` plus a
  ``<name>.meta.json`` sidecar recording ``origin: synthetic``, the generator version, the example
  count, and the source refs — no network, no clock, no randomness.
- **Deterministic.** The same seeds + count produce byte-identical files, so a generated dataset is
  reviewable and reproducible.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalglass.core.authority import DatasetStatus
from evalglass.harness._safe_fs import assert_within_root, refuse_symlinks, safe_name
from evalglass.harness.governance import GovernanceError, import_synthetic_dataset

#: The generator's identity, recorded in every dataset's metadata sidecar.
SYNTHETIC_GENERATOR_VERSION = "synthetic-generator@1"

_GENERATED_SUBDIR = ("evals", "datasets", "generated")


@dataclass(frozen=True)
class GeneratedDataset:
    """A generated dataset on disk: its JSONL path, metadata sidecar, and the proposed marker."""

    name: str
    dataset_path: Path
    metadata_path: Path
    example_count: int

    @property
    def status(self) -> DatasetStatus:
        # Synthetic data can never self-validate: its status is always proposed until a host
        # creates a separate validation record (governance.py / ADR 0021).
        return DatasetStatus.PROPOSED


def _expand(seed_examples: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    """Deterministically expand the seed corpus into ``count`` examples (cycle, clean copies).

    No randomness and no clock: example ``i`` is a copy of seed ``i % len(seeds)``, so the output is
    fully reproducible. Generation novelty is not the point — governance (forced ``proposed`` +
    reviewable provenance) is.
    """
    return [dict(seed_examples[i % len(seed_examples)]) for i in range(count)]


def generate_synthetic_dataset(
    name: str,
    *,
    root: Path,
    seed_examples: Sequence[Mapping[str, Any]],
    count: int,
    source_refs: Sequence[str] = (),
    generator_version: str = SYNTHETIC_GENERATOR_VERSION,
) -> GeneratedDataset:
    """Generate a proposed synthetic dataset under ``evals/datasets/generated/`` (fail-closed).

    Refuses a blank/unsafe ``name``, a ``count < 1``, or an empty ``seed_examples`` with a
    :class:`~evalglass.harness.governance.GovernanceError`. The dataset is imported through
    :func:`import_synthetic_dataset`, so its status is forced to ``proposed`` regardless of any
    caller claim.
    """
    safe = safe_name(name, kind="synthetic dataset name")
    if count < 1:
        raise GovernanceError(f"synthetic generation count must be >= 1, got {count}")
    if not seed_examples:
        raise GovernanceError("synthetic generation needs at least one seed example")

    examples = _expand(seed_examples, count)
    out_dir = root.joinpath(*_GENERATED_SUBDIR)
    dataset_path = out_dir / f"{safe}.jsonl"
    metadata_path = out_dir / f"{safe}.meta.json"

    # Fail closed if any existing path component or output file is a symlink: mkdir/write_text would
    # follow it and clobber a file outside the generated dataset tree (mirrors the optimizer
    # handoff and other harness write surfaces).
    refuse_symlinks(root, [*_GENERATED_SUBDIR, f"{safe}.jsonl"])
    refuse_symlinks(root, [*_GENERATED_SUBDIR, f"{safe}.meta.json"])
    assert_within_root(root, dataset_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        "".join(json.dumps(example, sort_keys=True) + "\n" for example in examples),
        encoding="utf-8",
    )

    # Route through the governance funnel: the status is forced to proposed (never self-validates).
    synthetic = import_synthetic_dataset(safe, len(examples))
    metadata = {
        "name": safe,
        "origin": "synthetic",
        "status": synthetic.status.value,
        "generator_version": generator_version,
        "example_count": len(examples),
        "seed_count": len(seed_examples),
        "source_refs": list(source_refs),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    return GeneratedDataset(
        name=safe,
        dataset_path=dataset_path,
        metadata_path=metadata_path,
        example_count=len(examples),
    )
