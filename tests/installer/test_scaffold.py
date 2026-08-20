"""S3 (EG-M3-3) — scaffold host-owned assets with safe (informational) defaults.

The skill scaffolds starter host-owned truth (config, sample dataset/trace, a host
evaluator template, an empty approval ledger, README) so a fresh install is useful
out of the box — but **never** authoritative: every metric is informational, the
dataset is proposed, no threshold is approved, and the AuthorityRecord is empty. The
scaffold preserves any existing host file (never clobbers host truth), and host
evaluators live outside the managed ``_evalglass/`` tree and target the vendored
runtime namespace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalglass.harness.loader import load_config
from evalglass.installer.contracts import AuthorityRecord, InstallerError
from evalglass.installer.plan import build_plan
from evalglass.installer.scaffold import SCAFFOLD_PATHS, scaffold


def _host(tmp_path: Path) -> Path:
    host = tmp_path / "host"
    host.mkdir()
    return host


def test_scaffold_writes_host_assets(tmp_path: Path) -> None:
    host = _host(tmp_path)
    result = scaffold(host)
    expected = [
        "evals/evalglass.yaml",
        "evals/datasets/sample.jsonl",
        "evals/traces/sample.jsonl",
        "evals/evaluators/answer_nonempty.py",
        "evals/authority.json",
        "evals/README.md",
    ]
    for rel in expected:
        assert (host / rel).is_file(), rel
        assert rel in result.created


def test_scaffolded_config_parses_all_informational(tmp_path: Path) -> None:
    host = _host(tmp_path)
    scaffold(host)
    cfg = load_config(str(host / "evals" / "evalglass.yaml"))
    assert cfg.metrics, "scaffolded config must declare metrics"
    for m in cfg.metrics:
        assert m.metric_status.value == "informational", m.spec.name
        assert m.threshold_approval.value == "proposed", m.spec.name
    for d in cfg.datasets:
        assert d.status.value == "proposed", d.name


def test_scaffold_authority_record_is_empty(tmp_path: Path) -> None:
    host = _host(tmp_path)
    scaffold(host)
    rec = AuthorityRecord.from_dict(json.loads((host / "evals" / "authority.json").read_text()))
    assert not rec.grants_any_authority()


def test_scaffold_preserves_existing_host_files(tmp_path: Path) -> None:
    host = _host(tmp_path)
    (host / "evals").mkdir()
    cfg = host / "evals" / "evalglass.yaml"
    cfg.write_text("custom: true\n", encoding="utf-8")
    result = scaffold(host)
    assert cfg.read_text(encoding="utf-8") == "custom: true\n", "scaffold clobbered host config"
    assert "evals/evalglass.yaml" in result.preserved
    assert "evals/evalglass.yaml" not in result.created


def test_scaffold_evaluator_outside_managed_and_uses_vendored_namespace(tmp_path: Path) -> None:
    host = _host(tmp_path)
    scaffold(host)
    ev = host / "evals" / "evaluators" / "answer_nonempty.py"
    assert ev.is_file()
    # Host evaluator lives outside the framework-managed runtime dir.
    assert "_evalglass" not in ev.relative_to(host).as_posix()
    # ...and targets the vendored runtime namespace (the host has no `evalglass` package).
    assert "from _evalglass.core import" in ev.read_text(encoding="utf-8")


def test_authority_record_round_trip() -> None:
    rec = AuthorityRecord(
        approved_thresholds=["exact_match"], validated_datasets=["datasets/gold.jsonl"]
    )
    assert AuthorityRecord.from_dict(rec.to_dict()) == rec
    assert rec.grants_any_authority()


def test_authority_record_empty_grants_nothing() -> None:
    assert not AuthorityRecord().grants_any_authority()


def test_authority_record_rejects_bad_type() -> None:
    with pytest.raises(InstallerError):
        AuthorityRecord.from_dict({"approved_thresholds": "not-a-list"})


def test_scaffold_creates_exactly_the_declared_paths(tmp_path: Path) -> None:
    """The files scaffold writes are exactly the single-sourced SCAFFOLD_PATHS."""
    host = _host(tmp_path)
    result = scaffold(host)
    assert sorted(result.created) == sorted(SCAFFOLD_PATHS)


def test_plan_lists_every_scaffolded_file(tmp_path: Path) -> None:
    """plan/install contract: `plan` proposes exactly what `install` will scaffold (no drift)."""
    from evalglass.installer.discovery import discover

    host = _host(tmp_path)
    (host / "src").mkdir()
    (host / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    plan = build_plan(discover(host))
    assert set(plan.proposed_host_assets) == set(SCAFFOLD_PATHS)


def test_readme_run_command_is_importable(tmp_path: Path) -> None:
    """The generated first-run command must put the vendored _evalglass on the path."""
    host = _host(tmp_path)
    scaffold(host)
    readme = (host / "evals" / "README.md").read_text(encoding="utf-8")
    assert "PYTHONPATH=evals" in readme
    assert "_evalglass.harness.cli" in readme


def test_readme_checklist_names_all_human_approvals(tmp_path: Path) -> None:
    """EG-M3-4: the checklist names every host-owned approval required before gating."""
    host = _host(tmp_path)
    scaffold(host)
    readme = (host / "evals" / "README.md").read_text(encoding="utf-8").lower()
    for item in ("validate gold", "threshold", "calibrat", "baseline", "data policy", "gating"):
        assert item in readme, f"checklist missing: {item}"


def test_scaffold_writes_ci_snippet(tmp_path: Path) -> None:
    host = _host(tmp_path)
    result = scaffold(host)
    ci = host / "evals" / "ci" / "github-actions.yml"
    assert ci.is_file()
    assert "evals/ci/github-actions.yml" in result.created


def test_ci_snippet_runs_vendored_runtime_only(tmp_path: Path) -> None:
    """The CI snippet invokes the vendored runtime — never the integration-time skill."""
    host = _host(tmp_path)
    scaffold(host)
    ci = (host / "evals" / "ci" / "github-actions.yml").read_text(encoding="utf-8")
    assert "_evalglass.harness.cli" in ci
    assert "PYTHONPATH=evals" in ci
    assert "evalglass-install" not in ci  # CI must not depend on the skill after install
