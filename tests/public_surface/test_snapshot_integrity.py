"""FS-UPD-1 — snapshot integrity + the deliberate-update gate (EG-AT1-3).

There is **no ``--snapshot-update`` escape hatch**: to change a golden you edit the
golden and the test literal in the same reviewed commit. This guard keeps every
committed snapshot canonical (parses + ``sort_keys``-stable, so diffs are minimal
and reviewable) and proves the product ships no flag that would auto-bless drifted
output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.public_surface._normalize import is_sort_key_stable

_SNAP = Path(__file__).parent / "_snapshots"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.public_surface
def test_all_json_snapshots_parse_and_are_sort_stable() -> None:
    snapshots = sorted(_SNAP.glob("*.json"))
    assert snapshots, "no JSON snapshots found"
    for path in snapshots:
        text = path.read_text(encoding="utf-8")
        json.loads(text)  # must parse
        assert is_sort_key_stable(text), (
            f"{path.name} is not sort_keys-canonical; regenerate it with "
            "json.dumps(..., indent=2, sort_keys=True)"
        )


@pytest.mark.public_surface
def test_no_snapshot_update_flag_in_product() -> None:
    """The vendored product offers no flag that auto-overwrites a golden from output."""
    src = _REPO_ROOT / "src" / "evalglass"
    offenders = [
        path.relative_to(_REPO_ROOT).as_posix()
        for path in src.rglob("*.py")
        if "snapshot-update" in (body := path.read_text(encoding="utf-8"))
        or "snapshot_update" in body
    ]
    assert not offenders, f"product exposes a snapshot-update escape hatch: {offenders}"
