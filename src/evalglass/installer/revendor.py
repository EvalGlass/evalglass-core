"""Safe re-vendoring: dry-run, host-patch detection, confirm-to-clobber (EG-M3-5).

Re-running the skill against an installed host must be safe and reviewable. ``plan_revendor``
diffs what the framework *would* vendor (via :func:`evalglass.installer.vendor.managed_files`)
against the recorded manifest and the bytes on disk, classifying each managed file as
replace / add / remove / host-patched — and **writes nothing**. ``revendor`` applies the plan,
but **refuses** to clobber a host-patched managed file (or remove one) unless ``confirm=True``,
and never touches host-owned truth (only managed files under ``_evalglass/``). Stdlib-only.

This is integration-time code; the runtime never imports it (ADR 0010).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Self

from evalglass.installer.contracts import InstallerError, ManagedFileRecord, VendorManifest
from evalglass.installer.vendor import MANAGED_ROOT, managed_files, write_manifest_and_lock


@dataclass(frozen=True)
class RevendorPlan:
    """What a re-vendor would change. ``requires_confirmation`` guards host-patch loss."""

    replace: list[str] = field(default_factory=list)
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    host_patched: list[str] = field(default_factory=list)
    unchanged: int = 0

    def requires_confirmation(self) -> bool:
        # Destroying a host edit to a managed file (replace or remove it) needs explicit confirm.
        destructive = set(self.replace) | set(self.remove)
        return any(p in destructive for p in self.host_patched)

    def to_dict(self) -> dict[str, Any]:
        return {
            "replace": list(self.replace),
            "add": list(self.add),
            "remove": list(self.remove),
            "host_patched": list(self.host_patched),
            "unchanged": self.unchanged,
            "requires_confirmation": self.requires_confirmation(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            replace=list(data.get("replace", [])),
            add=list(data.get("add", [])),
            remove=list(data.get("remove", [])),
            host_patched=list(data.get("host_patched", [])),
            unchanged=int(data.get("unchanged", 0)),
        )


def _validate_managed_path(rel: str) -> None:
    """Fail closed unless ``rel`` is a relative path strictly under the managed root.

    A corrupted or host-edited manifest must not be able to steer a remove/write at a
    host-owned path (e.g. ``evals/evalglass.yaml``) or escape via ``..`` — that would break
    the guarantee that re-vendoring only ever touches files under ``evals/_evalglass/``.
    """
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not rel.startswith(f"{MANAGED_ROOT}/"):
        raise InstallerError(
            f"revendor: manifest path {rel!r} is not under the managed root {MANAGED_ROOT!r}"
        )


def _load_manifest(host_root: Path) -> VendorManifest:
    path = host_root / MANAGED_ROOT / "vendor-manifest.json"
    if not path.is_file():
        raise InstallerError(
            f"revendor: no vendor manifest at {path} — run `install` before re-vendoring"
        )
    try:
        manifest = VendorManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, InstallerError) as exc:
        raise InstallerError(f"revendor: vendor manifest is invalid: {exc}") from exc
    for record in manifest.files:
        _validate_managed_path(record.path)
    return manifest


def _disk_sha(host_root: Path, rel: str) -> str | None:
    p = host_root / rel
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def plan_revendor(framework_pkg: Path, host_root: Path, *, framework_version: str) -> RevendorPlan:
    """Compute the re-vendor diff (read-only) against the recorded manifest and disk."""
    host_root = Path(host_root)
    manifest = _load_manifest(host_root)
    recorded = {r.path: r.sha256 for r in manifest.files}
    new = {mc.path: mc.sha256 for mc in managed_files(framework_pkg, framework_version)}

    replace: list[str] = []
    add: list[str] = []
    unchanged = 0
    for path, new_sha in sorted(new.items()):
        disk = _disk_sha(host_root, path)
        if path not in recorded or disk is None:
            # New file, or a recorded managed file deleted locally — (re)write it so the
            # vendored runtime stays complete after a re-vendor.
            add.append(path)
        elif new_sha != recorded[path]:
            replace.append(path)
        else:
            unchanged += 1
    remove = sorted(p for p in recorded if p not in new)

    # A managed file whose on-disk bytes differ from the recorded checksum is a host patch.
    host_patched = sorted(
        path
        for path, sha in recorded.items()
        if (disk := _disk_sha(host_root, path)) is not None and disk != sha
    )
    return RevendorPlan(
        replace=replace, add=add, remove=remove, host_patched=host_patched, unchanged=unchanged
    )


def revendor(
    framework_pkg: Path,
    host_root: Path,
    *,
    framework_version: str,
    source_ref: str | None = None,
    confirm: bool = False,
) -> RevendorPlan:
    """Apply a re-vendor. Refuses to clobber a host-patched managed file unless ``confirm``."""
    host_root = Path(host_root)
    plan = plan_revendor(framework_pkg, host_root, framework_version=framework_version)
    if plan.requires_confirmation() and not confirm:
        clobbered = sorted(set(plan.host_patched) & (set(plan.replace) | set(plan.remove)))
        raise InstallerError(
            "revendor: would overwrite/remove host-patched managed file(s) "
            f"{clobbered}; re-run with confirm=True to proceed (the patch will be lost)"
        )

    contents = managed_files(framework_pkg, framework_version)
    records = [
        ManagedFileRecord(path=mc.path, sha256=mc.sha256, purpose=mc.purpose) for mc in contents
    ]
    # Apply replaces/adds (only managed files under the managed root are ever written).
    write_set = set(plan.replace) | set(plan.add)
    for mc in contents:
        if mc.path in write_set:
            dest = host_root / mc.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(mc.content.encode("utf-8"))  # LF preserved (see vendor.vendor)
    # Remove obsolete managed files no longer in the framework.
    for rel in plan.remove:
        target = host_root / rel
        if target.is_file():
            target.unlink()

    write_manifest_and_lock(
        host_root, records, framework_version=framework_version, source_ref=source_ref
    )
    return plan
