"""S5 (EG-M3-5) — safe re-vendoring: dry-run, host-patch detection, confirm, removal.

Re-running the skill against an installed host must be safe and reviewable (EG-M3-5):
a dry-run lists exactly the managed files that would change and writes nothing; an
ordinary re-vendor is idempotent; a host edit to a *managed* file is detected as a
host patch and is never silently clobbered (a destructive replace/remove requires
explicit confirmation); obsolete managed files are cleaned up; and host-owned truth is
never touched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import evalglass
from evalglass.installer.contracts import InstallerError
from evalglass.installer.revendor import RevendorPlan, plan_revendor, revendor
from evalglass.installer.scaffold import scaffold
from evalglass.installer.vendor import vendor

_FRAMEWORK_PKG = Path(evalglass.__file__).resolve().parent


def _install(host: Path, version: str = "1.0.0") -> None:
    host.mkdir(parents=True, exist_ok=True)
    vendor(_FRAMEWORK_PKG, host, framework_version=version, source_ref="test")
    scaffold(host)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_revendor_same_version_is_idempotent(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    plan = revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert isinstance(plan, RevendorPlan)
    assert plan.replace == []
    assert plan.add == []
    assert plan.remove == []


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    before = _snapshot(host)
    plan_revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0")
    assert _snapshot(host) == before, "dry-run mutated the host"


def test_revendor_version_bump_replaces_init(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    plan = plan_revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0")
    assert "evals/_evalglass/__init__.py" in plan.replace
    revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0")
    assert '__version__ = "2.0.0"' in (host / "evals" / "_evalglass" / "__init__.py").read_text()


def test_revendor_detects_host_patch(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    patched = host / "evals" / "_evalglass" / "core" / "engine.py"
    patched.write_text(patched.read_text() + "\n# host patch\n", encoding="utf-8")
    plan = plan_revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert "evals/_evalglass/core/engine.py" in plan.host_patched


def test_revendor_refuses_to_clobber_host_patch_without_confirm(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    init = host / "evals" / "_evalglass" / "__init__.py"
    init.write_text(init.read_text() + "\n# host patch\n", encoding="utf-8")
    # A version bump would replace __init__.py, which the host has patched → needs confirm.
    plan = plan_revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0")
    assert "evals/_evalglass/__init__.py" in plan.host_patched
    assert plan.requires_confirmation()
    with pytest.raises(InstallerError):
        revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0")
    assert "# host patch" in init.read_text(), "refused revendor must not have clobbered the patch"
    # With explicit confirmation it proceeds and restores the framework file.
    revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0", confirm=True)
    text = init.read_text()
    assert "# host patch" not in text
    assert '__version__ = "2.0.0"' in text


def test_revendor_preserves_host_owned(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    ds = host / "evals" / "datasets" / "sample.jsonl"
    before = ds.read_bytes()
    revendor(_FRAMEWORK_PKG, host, framework_version="2.0.0", confirm=True)
    assert ds.read_bytes() == before, "re-vendoring touched host-owned truth"


def test_revendor_removes_obsolete_managed_file(tmp_path: Path) -> None:
    host = tmp_path / "host"
    _install(host, "1.0.0")
    managed = host / "evals" / "_evalglass"
    gone = managed / "core" / "_gone.py"
    gone.write_text("x = 1\n", encoding="utf-8")
    manifest_path = managed / "vendor-manifest.json"
    m = json.loads(manifest_path.read_text())
    m["files"].append(
        {
            "path": "evals/_evalglass/core/_gone.py",
            "sha256": hashlib.sha256(b"x = 1\n").hexdigest(),
            "purpose": "core",
        }
    )
    manifest_path.write_text(json.dumps(m), encoding="utf-8")
    plan = plan_revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert "evals/_evalglass/core/_gone.py" in plan.remove
    revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert not gone.exists()


def test_revendor_rejects_manifest_path_outside_managed_root(tmp_path: Path) -> None:
    """A manifest path outside _evalglass/ must fail closed, never unlink host truth."""
    host = tmp_path / "host"
    _install(host, "1.0.0")
    mp = host / "evals" / "_evalglass" / "vendor-manifest.json"
    m = json.loads(mp.read_text())
    m["files"].append({"path": "evals/evalglass.yaml", "sha256": "x", "purpose": "core"})
    mp.write_text(json.dumps(m), encoding="utf-8")
    victim = host / "evals" / "evalglass.yaml"
    victim.write_text("HOST OWNED\n", encoding="utf-8")
    with pytest.raises(InstallerError):
        plan_revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert victim.read_text() == "HOST OWNED\n", "a bad manifest path removed a host-owned file"


def test_revendor_restores_deleted_managed_file(tmp_path: Path) -> None:
    """A locally-deleted managed file is restored on re-vendor (the runtime stays complete)."""
    host = tmp_path / "host"
    _install(host, "1.0.0")
    engine = host / "evals" / "_evalglass" / "core" / "engine.py"
    engine.unlink()
    plan = plan_revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert "evals/_evalglass/core/engine.py" in plan.add
    revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")
    assert engine.is_file()


def test_vendored_files_use_lf_newlines(tmp_path: Path) -> None:
    """Managed files are written byte-for-byte (LF) so manifest checksums match cross-platform."""
    host = tmp_path / "host"
    _install(host, "1.0.0")
    for py in (host / "evals" / "_evalglass").rglob("*.py"):
        assert b"\r\n" not in py.read_bytes(), py


def test_revendor_without_manifest_is_setup_error(tmp_path: Path) -> None:
    host = tmp_path / "host"
    host.mkdir()
    with pytest.raises(InstallerError):
        plan_revendor(_FRAMEWORK_PKG, host, framework_version="1.0.0")


def test_revendor_plan_round_trip() -> None:
    plan = RevendorPlan(replace=["a"], add=["b"], remove=["c"], host_patched=["a"], unchanged=5)
    assert RevendorPlan.from_dict(plan.to_dict()) == plan
    assert plan.requires_confirmation()  # 'a' is both host_patched and replaced
