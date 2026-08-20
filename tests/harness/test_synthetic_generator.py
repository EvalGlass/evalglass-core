"""Synthetic dataset generator + synthetic-origin authority proof (EG-H3-1, EG-H3-2).

The generator is a real, stdlib-only local capability that deterministically expands host-provided
seed examples into a generated dataset on disk, with a reviewable metadata sidecar, routed through
the proposed-forcing governance funnel. It never self-validates: a generated dataset is always
``proposed``, and synthetic-origin data can never resolve ``can_gate=true``.

The specificity control proves the guard is not a blanket deny — a host-validated (non-synthetic)
dataset under the same preconditions remains eligible to gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.core.authority import (
    AuthorityInputs,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.contracts import DataPolicy
from evalglass.harness.governance import GovernanceError, import_synthetic_dataset
from evalglass.harness.synthetic import (
    SYNTHETIC_GENERATOR_VERSION,
    GeneratedDataset,
    generate_synthetic_dataset,
)

_SEEDS = [
    {"input": "2+2", "output": "4", "reference": "4"},
    {"input": "3+3", "output": "6", "reference": "6"},
]
_GENERATED_REL = "evals/datasets/generated"


def _generate(root: Path, *, name: str = "demo", count: int = 5) -> GeneratedDataset:
    return generate_synthetic_dataset(
        name, root=root, seed_examples=_SEEDS, count=count, source_refs=("seed-corpus@1",)
    )


# --------------------------------------------------------------------------- #
# EG-H3-1 — generation: proposed-only, local files, reviewable metadata        #
# --------------------------------------------------------------------------- #
def test_generated_dataset_status_is_always_proposed(tmp_path: Path) -> None:
    assert _generate(tmp_path).status is DatasetStatus.PROPOSED


def test_generation_writes_local_jsonl_and_reviewable_metadata(tmp_path: Path) -> None:
    generated = _generate(tmp_path, count=5)
    assert generated.dataset_path == tmp_path / _GENERATED_REL / "demo.jsonl"
    rows = [
        json.loads(line)
        for line in generated.dataset_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(rows) == 5
    metadata = json.loads(generated.metadata_path.read_text(encoding="utf-8"))
    assert metadata["origin"] == "synthetic"
    assert metadata["status"] == "proposed"
    assert metadata["generator_version"] == SYNTHETIC_GENERATOR_VERSION
    assert metadata["example_count"] == 5
    assert metadata["source_refs"] == ["seed-corpus@1"]


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Same seeds + count -> byte-identical dataset and metadata (no randomness, no clock)."""
    a = _generate(tmp_path / "a", count=4)
    b = _generate(tmp_path / "b", count=4)
    assert a.dataset_path.read_bytes() == b.dataset_path.read_bytes()
    assert a.metadata_path.read_bytes() == b.metadata_path.read_bytes()


def test_generator_uses_no_network(tmp_path: Path) -> None:
    from evalglass.harness import synthetic as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("import socket", "urllib", "import requests", "from requests", "httpx", "http.client")
    assert [t for t in banned if t in src] == []


@pytest.mark.parametrize(
    ("name", "count", "seeds"),
    [
        ("demo", 0, _SEEDS),  # count < 1
        ("demo", 5, []),  # no seeds
        ("../evil", 5, _SEEDS),  # path traversal in the name
        ("nested/name", 5, _SEEDS),  # path separator in the name
    ],
)
def test_generation_fails_closed_on_bad_input(
    tmp_path: Path, name: str, count: int, seeds: list[dict[str, str]]
) -> None:
    with pytest.raises(GovernanceError):
        generate_synthetic_dataset(name, root=tmp_path, seed_examples=seeds, count=count)


def test_generation_refuses_symlinked_output_target(tmp_path: Path) -> None:
    """Fail-closed: a pre-planted symlink at the dataset path is refused before any write, so the
    generator cannot follow it to clobber a file outside the generated tree."""
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("host secret\n", encoding="utf-8")
    out_dir = tmp_path / _GENERATED_REL
    out_dir.mkdir(parents=True)
    (out_dir / "demo.jsonl").symlink_to(outside)

    with pytest.raises(GovernanceError):
        _generate(tmp_path, name="demo")
    assert outside.read_text(encoding="utf-8") == "host secret\n"  # never followed/overwritten


# --------------------------------------------------------------------------- #
# EG-H3-2 — synthetic-origin data cannot gate; host-validated specificity      #
# --------------------------------------------------------------------------- #
def _gating_inputs(dataset_status: DatasetStatus) -> AuthorityInputs:
    """Otherwise fully-authorized inputs, parameterized only by dataset status."""
    return AuthorityInputs(
        metric_status=MetricStatus.GATING,
        dataset_status=dataset_status,
        threshold_approval=ThresholdApproval.APPROVED,
        data_policy=DataPolicy.PERMITTED,
        judge_calibration=JudgeCalibration.CALIBRATED,
    )


def test_synthetic_origin_data_cannot_gate(tmp_path: Path) -> None:
    """A generated dataset's status (proposed) yields can_gate=false with a dataset_proposed reason,
    even with a gating metric, approved threshold, and permitted policy."""
    generated = _generate(tmp_path)
    resolved = resolve_authority(_gating_inputs(generated.status))
    assert resolved.can_gate is False
    assert "dataset_proposed" in resolved.reasons


@pytest.mark.parametrize("declared", ["validated", "approved", "gating"])
def test_declared_status_is_stripped_by_the_import_funnel(declared: str) -> None:
    """A generator claim of validated/approved/gating is made safe, never honored."""
    assert (
        import_synthetic_dataset("x", 3, declared_status=declared).status is DatasetStatus.PROPOSED
    )


def test_specificity_host_validated_dataset_remains_eligible_to_gate() -> None:
    """The guard is not a blanket deny: a host-validated (non-synthetic) dataset under the same
    preconditions resolves can_gate=true."""
    resolved = resolve_authority(_gating_inputs(DatasetStatus.VALIDATED))
    assert resolved.can_gate is True
    assert resolved.reasons == []
