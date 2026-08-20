"""S1 (EG-M3-1) — skill contract round-trips + fail-closed parsing.

The skill's typed artifacts (HostDiscoveryReport, InstallPlan, DataPolicyPrompt)
are JSON-primary and must parse fail-closed, exactly like the core contracts: a
missing/malformed field is rejected with InstallerError, never silently coerced.
"""

from __future__ import annotations

import pytest

from evalglass.installer.contracts import (
    DataPolicyPrompt,
    HostDiscoveryReport,
    InstallerError,
    InstallPlan,
)


def test_data_policy_prompt_round_trip() -> None:
    p = DataPolicyPrompt(
        subject="datasets/gold.jsonl",
        question="May this dataset's contents leave the process for replay?",
        choices=["permitted", "redacted", "forbidden"],
    )
    assert DataPolicyPrompt.from_dict(p.to_dict()) == p


def test_data_policy_prompt_rejects_missing_field() -> None:
    with pytest.raises(InstallerError):
        DataPolicyPrompt.from_dict({"subject": "x", "question": "y"})  # no choices


def test_data_policy_prompt_rejects_empty_choices() -> None:
    with pytest.raises(InstallerError):
        DataPolicyPrompt.from_dict({"subject": "x", "question": "y", "choices": []})


def test_host_discovery_report_round_trip() -> None:
    report = HostDiscoveryReport(
        root="/work/host",
        language="python",
        has_evals_dir=False,
        llm_call_sites=[{"file": "app.py", "line": 12, "callee": "client.chat.completions.create"}],
        trace_candidates=["logs/traces.jsonl"],
        eval_assets=[],
        ci_configs=[".github/workflows/ci.yml"],
        ignore_files=[".gitignore"],
        data_policy_prompts=[
            DataPolicyPrompt(subject="logs/traces.jsonl", question="egress?", choices=["forbidden"])
        ],
        open_questions=["No gold dataset found; reference metrics cannot run yet."],
    )
    assert HostDiscoveryReport.from_dict(report.to_dict()) == report


def test_host_discovery_report_rejects_non_mapping() -> None:
    with pytest.raises(InstallerError):
        HostDiscoveryReport.from_dict([])  # type: ignore[arg-type]


def test_host_discovery_report_rejects_missing_root() -> None:
    with pytest.raises(InstallerError):
        HostDiscoveryReport.from_dict({"language": "python"})


def test_install_plan_round_trip() -> None:
    plan = InstallPlan(
        root="/work/host",
        managed_root="evals/_evalglass",
        proposed_host_assets=["evals/evalglass.yaml", "evals/datasets/sample.jsonl"],
        preserved_paths=["evals/datasets/gold.jsonl"],
        questions=[DataPolicyPrompt(subject="x", question="egress?", choices=["forbidden"])],
        blockers=[],
    )
    assert InstallPlan.from_dict(plan.to_dict()) == plan


def test_install_plan_is_never_authoritative() -> None:
    """The plan can propose assets but must never claim to grant gating authority."""
    plan = InstallPlan(
        root="/work/host",
        managed_root="evals/_evalglass",
        proposed_host_assets=["evals/evalglass.yaml"],
        preserved_paths=[],
        questions=[],
        blockers=[],
    )
    # Proposed host assets are non-authoritative by contract; the plan exposes that.
    assert plan.grants_authority is False
    assert "evals/evalglass.yaml" in plan.proposed_host_assets


def test_install_plan_rejects_bad_questions() -> None:
    with pytest.raises(InstallerError):
        InstallPlan.from_dict(
            {
                "root": "/work/host",
                "managed_root": "evals/_evalglass",
                "proposed_host_assets": [],
                "preserved_paths": [],
                "questions": ["not-a-prompt-mapping"],
                "blockers": [],
            }
        )
