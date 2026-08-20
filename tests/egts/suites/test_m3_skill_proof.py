"""EGTS-M3 — Skill Proof: discovery, vendoring boundaries, safe scaffold, runtime independence.

Drives the **real** integration-time skill surfaces (``evalglass.installer`` + the vendored
``_evalglass`` runtime) against disposable host repos in isolated fixtures, checking typed
artifacts (HostDiscoveryReport, InstallPlan, vendor-manifest, evalglass.lock, the persisted
Scorecard) and proving each checker family fails for the right reason (negative controls).

- **EGTS-M3-1** discovery/plan are read-only; the plan separates proposed from preserved.
- **EGTS-M3-2** the manifest/lock record the managed boundary honestly; host truth is preserved.
- **EGTS-M3-3** a fresh install's first run is informational (no silent authority).
- **EGTS-M3-4** the vendored runtime runs with the skill gone (runtime independence).
- **EGTS-M3-5** re-vendoring is read-only in dry-run and refuses to clobber a host patch.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import evalglass
from evalglass.core import (
    AuthorityLevel,
    ResolvedAuthority,
    Scorecard,
    Verdict,
    VerdictPayload,
)
from evalglass.installer import (
    InstallerError,
    VendorManifest,
    build_plan,
    discover,
    plan_revendor,
    revendor,
    scaffold,
    vendor,
)
from evalglass.installer.contracts import EvalglassLock, ManagedFileRecord
from tests.egts.checkers import (
    CheckerError,
    check_host_file_unchanged,
    check_lock_records_runtime,
    check_managed_boundary,
    check_manifest_checksums,
    check_no_host_mutation,
    check_no_silent_authority,
)
from tests.egts.host_repo import make_host_repo, snapshot

_FW = Path(evalglass.__file__).resolve().parent
_VERSION = evalglass.__version__


def _install(host: Path) -> None:
    vendor(_FW, host, framework_version=_VERSION, source_ref="egts")
    scaffold(host)


def _load_manifest(host: Path) -> VendorManifest:
    raw = (host / "evals" / "_evalglass" / "vendor-manifest.json").read_text()
    return VendorManifest.from_dict(json.loads(raw))


def _load_lock(host: Path) -> EvalglassLock:
    return EvalglassLock.from_dict(json.loads((host / "evals" / "evalglass.lock").read_text()))


# === EGTS-M3-1 — discovery / plan are read-only =============================


def test_discover_is_read_only(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.discover.readonly").root
    before = snapshot(host)
    report = discover(host)
    check_no_host_mutation(before, snapshot(host))
    assert report.language == "python"
    assert any("app.py" in c["file"] for c in report.llm_call_sites)


def test_no_mutation_checker_detects_mutation(tmp_path: Path) -> None:
    """Negative control: the read-only checker really fails when the host changed."""
    host = make_host_repo(tmp_path, "m3.discover.nc").root
    before = snapshot(host)
    (host / "src" / "injected.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(CheckerError):
        check_no_host_mutation(before, snapshot(host))


def test_plan_separates_proposed_from_preserved(tmp_path: Path) -> None:
    # Seed a path the scaffolder WOULD propose, so the separation is actually exercised
    # (gold.jsonl would be absent from proposed anyway — a vacuous assertion).
    host = make_host_repo(
        tmp_path, "m3.plan", files={"evals/datasets/sample.jsonl": '{"input": 1}\n'}
    ).root
    plan = build_plan(discover(host))
    assert "evals/datasets/sample.jsonl" in plan.preserved_paths
    assert "evals/datasets/sample.jsonl" not in plan.proposed_host_assets
    assert plan.grants_authority is False


# === EGTS-M3-2 — vendoring manifest / lock / boundary =======================


def test_install_records_managed_boundary_and_lock(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.install").root
    _install(host)
    manifest = _load_manifest(host)
    check_managed_boundary(manifest)
    check_manifest_checksums(host, manifest)
    check_lock_records_runtime(_load_lock(host))


def test_install_preserves_host_owned_truth(tmp_path: Path) -> None:
    # Seed a file the scaffolder WOULD otherwise create, so this proves the overwrite guard
    # (a non-colliding path like gold.jsonl would pass even if install clobbered host truth).
    custom = "run:\n  id: my-host\n"
    host = make_host_repo(tmp_path, "m3.preserve", files={"evals/evalglass.yaml": custom}).root
    before = (host / "evals" / "evalglass.yaml").read_bytes()
    _install(host)
    check_host_file_unchanged(host / "evals" / "evalglass.yaml", before)


def test_managed_boundary_checker_detects_host_path(tmp_path: Path) -> None:
    """Negative control: a manifest claiming a host-owned path fails the boundary checker."""
    bad = VendorManifest(
        schema_version="1",
        source_version="1.0.0",
        managed_root="evals/_evalglass",
        files=[ManagedFileRecord(path="evals/evalglass.yaml", sha256="x", purpose="core")],
    )
    with pytest.raises(CheckerError):
        check_managed_boundary(bad)


def test_manifest_checksum_checker_detects_drift(tmp_path: Path) -> None:
    """Negative control: editing a managed file makes the checksum checker fail."""
    host = make_host_repo(tmp_path, "m3.drift").root
    _install(host)
    engine = host / "evals" / "_evalglass" / "core" / "engine.py"
    engine.write_text(engine.read_text() + "\n# drift\n", encoding="utf-8")
    with pytest.raises(CheckerError):
        check_manifest_checksums(host, _load_manifest(host))


# === EGTS-M3-3 — no silent authority (real vendored runtime) ================


def _run_vendored(host: Path) -> subprocess.CompletedProcess[str]:
    env = {"PYTHONPATH": str(host / "evals"), "PATH": os.environ.get("PATH", "")}
    return subprocess.run(
        [sys.executable, "-m", "_evalglass.harness.cli", "run", "--config", "evals/evalglass.yaml"],
        cwd=host,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_fresh_install_first_run_is_informational(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.firstrun").root
    _install(host)
    result = _run_vendored(host)
    assert result.returncode == 0, result.stderr
    assert "informational" in result.stdout
    # Check the typed artifact, not just the text: the persisted Scorecard grants no gate.
    scorecard_path = next((host / "evals" / "reports").rglob("scorecard.json"))
    scorecard = Scorecard.from_dict(json.loads(scorecard_path.read_text()))
    check_no_silent_authority(scorecard)


def test_no_silent_authority_checker_detects_a_gate(tmp_path: Path) -> None:
    """Negative control: a scorecard with an active gate fails the no-silent-authority checker."""
    gated = Scorecard(
        verdict=VerdictPayload(verdict=Verdict.PASS, ci_should_fail=False, passing_gates=["m"]),
        metrics=[],
        authority={
            "m": ResolvedAuthority(can_gate=True, level=AuthorityLevel.GATING, blocked=False)
        },
    )
    with pytest.raises(CheckerError):
        check_no_silent_authority(gated)


# === EGTS-M3-4 — runtime independence =======================================


def test_vendored_runtime_runs_without_skill(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.independence").root
    _install(host)
    assert not (host / "evals" / "_evalglass" / "skill").exists()
    result = _run_vendored(host)
    assert result.returncode == 0, result.stderr
    # The vendored tree imports nothing named `evalglass` (so it cannot bind an installed copy).
    for py in (host / "evals" / "_evalglass").rglob("*.py"):
        for line in py.read_text(encoding="utf-8").splitlines():
            assert not line.strip().startswith(("from evalglass", "import evalglass"))


def test_independence_check_detects_a_vendored_installer(tmp_path: Path) -> None:
    """Negative control: if `installer/` were vendored, it would be importable from the tree."""
    host = make_host_repo(tmp_path, "m3.independence.nc").root
    _install(host)
    leaked = host / "evals" / "_evalglass" / "installer"
    leaked.mkdir()
    (leaked / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    code = (
        "import sys, importlib.util; sys.path.insert(0, sys.argv[1]); "
        "print(importlib.util.find_spec('_evalglass.installer') is not None)"
    )
    result = subprocess.run(  # noqa: S603 — fixed interpreter, no shell, test-only
        [sys.executable, "-c", code, str(host / "evals")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == "True"  # the leak is detectable


# === EGTS-M3-5 — safe re-vendor / host preservation =========================


def test_revendor_dry_run_is_read_only(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.revendor.dryrun").root
    _install(host)
    before = snapshot(host)
    plan_revendor(_FW, host, framework_version="9.9.9")
    check_no_host_mutation(before, snapshot(host))


def test_revendor_refuses_to_clobber_host_patch(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.revendor.clobber").root
    _install(host)
    init = host / "evals" / "_evalglass" / "__init__.py"
    init.write_text(init.read_text() + "\n# host patch\n", encoding="utf-8")
    plan = plan_revendor(_FW, host, framework_version="9.9.9")
    assert plan.requires_confirmation()
    with pytest.raises(InstallerError):
        revendor(_FW, host, framework_version="9.9.9")
    assert "# host patch" in init.read_text()


def test_revendor_preserves_host_owned(tmp_path: Path) -> None:
    host = make_host_repo(tmp_path, "m3.revendor.preserve").root
    _install(host)
    ds = host / "evals" / "datasets" / "sample.jsonl"
    before = ds.read_bytes()
    revendor(_FW, host, framework_version="9.9.9", confirm=True)
    check_host_file_unchanged(ds, before)


def test_revendor_silent_clobber_would_lose_patch_without_guard(tmp_path: Path) -> None:
    """Negative control: confirm=True intentionally clobbers — the guard is what protects."""
    host = make_host_repo(tmp_path, "m3.revendor.nc").root
    _install(host)
    init = host / "evals" / "_evalglass" / "__init__.py"
    init.write_text(init.read_text() + "\n# host patch\n", encoding="utf-8")
    revendor(_FW, host, framework_version="9.9.9", confirm=True)
    assert "# host patch" not in init.read_text()
    digest = hashlib.sha256(init.read_bytes()).hexdigest()
    assert digest  # restored to the framework version
