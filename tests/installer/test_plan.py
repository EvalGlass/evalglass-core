"""S1 (EG-M3-1) — install planning separates proposed from authoritative.

`build_plan` turns a read-only discovery report into a reviewable InstallPlan
(acceptance: "Plan distinguishes proposed assets from authoritative host-owned
truth", "Missing host information is surfaced as a question or blocker"). The plan
proposes managed vendoring + host-owned scaffolds, preserves existing host truth,
and carries the open questions forward — it grants no authority.
"""

from __future__ import annotations

from evalglass.installer.contracts import DataPolicyPrompt, HostDiscoveryReport
from evalglass.installer.plan import build_plan


def _report(**overrides: object) -> HostDiscoveryReport:
    base: dict[str, object] = {
        "root": "/work/host",
        "language": "python",
        "has_evals_dir": False,
        "llm_call_sites": [],
        "trace_candidates": [],
        "eval_assets": [],
        "ci_configs": [],
        "ignore_files": [],
        "data_policy_prompts": [],
        "open_questions": [],
    }
    base.update(overrides)
    return HostDiscoveryReport(**base)  # type: ignore[arg-type]


def test_plan_proposes_managed_root_and_host_scaffolds() -> None:
    plan = build_plan(_report())
    assert plan.managed_root == "evals/_evalglass"
    # Proposes a config + sample assets, all host-owned and non-authoritative.
    assert any(a.endswith("evalglass.yaml") for a in plan.proposed_host_assets)
    assert plan.grants_authority is False


def test_plan_carries_questions_forward() -> None:
    prompt = DataPolicyPrompt(subject="logs/t.jsonl", question="egress?", choices=["forbidden"])
    plan = build_plan(_report(data_policy_prompts=[prompt]))
    assert prompt in plan.questions


def test_plan_preserves_existing_host_truth_not_proposes_it() -> None:
    """An existing eval asset is preserved (host truth), never proposed/overwritten."""
    plan = build_plan(_report(has_evals_dir=True, eval_assets=["evals/datasets/gold.jsonl"]))
    assert "evals/datasets/gold.jsonl" in plan.preserved_paths
    assert "evals/datasets/gold.jsonl" not in plan.proposed_host_assets


def test_plan_blocks_on_non_python_host() -> None:
    """Missing host information (an unsupported language) is a blocker, not a silent guess."""
    plan = build_plan(_report(language="unknown"))
    assert plan.blockers, "an unsupported host language must surface a blocker"
