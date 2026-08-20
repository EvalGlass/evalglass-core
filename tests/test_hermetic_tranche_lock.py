"""Hermetic tranche lock — live connectors deferred + CI stays hermetic (EG-H5-1, EG-H5-3).

The foundation/hermetic tranche keeps the live trace connectors (Langfuse / Phoenix / LangSmith)
deferred and the required CI tier offline. This guard pins those invariants so a future change that
makes a connector required, or that lets live egress into the required tier, fails *visibly*:

- the required CI tier runs ``-m "not live_lane"`` and never sets ``EVALGLASS_LIVE_LANES``;
- every ``live_lane`` job is gated on manual ``workflow_dispatch`` — never a push/PR gate;
- the docs/ontology/public-surface check is a separate named job, not folded into unit tests;
- the live connectors, once built (EG-R1/R2/R3) and covered (EG-R4), stay **opt-in** — each lane
  is conservatively mature and pins its own optional SDK extra, so ``covered`` never means the
  provider SDK entered the required runtime (the required-tier hermeticity above guarantees it).
  The exact post-R-tranche coverage end state is pinned by ``test_v2_coverage_registry``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from evalglass.harness.lanes import Maturity, built_in_lanes

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_COVERAGE = _ROOT / "tests" / "egts" / "coverage" / "eg_m5c.yaml"
_LIVE_ENV = "EVALGLASS_LIVE_LANES"


def _jobs() -> dict[str, Any]:
    return dict(yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"])


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(str(s.get("run", "")) for s in job.get("steps", []) if isinstance(s, dict))


def test_required_tier_excludes_live_lane() -> None:
    """A CI job runs the required tier with ``-m "not live_lane"`` (no live egress)."""
    assert any("not live_lane" in _run_text(job) for job in _jobs().values())


def test_live_lane_jobs_are_manual_dispatch_only() -> None:
    """Every job that runs the ``live_lane`` tier is gated on manual ``workflow_dispatch`` — so
    real egress can never run in the required PR/push tier."""
    live = [job for job in _jobs().values() if "-m live_lane" in _run_text(job)]
    assert live, "the live_lane job must exist (deferred connectors keep their placeholders)"
    for job in live:
        assert "workflow_dispatch" in str(job.get("if", ""))


def test_live_lanes_env_only_in_dispatch_jobs() -> None:
    """``EVALGLASS_LIVE_LANES`` is set only in a manual-dispatch job — the required tier never
    sets it, so the run stays double-guarded (marker + env)."""
    for job in _jobs().values():
        if _LIVE_ENV in yaml.safe_dump(job):
            assert "workflow_dispatch" in str(job.get("if", "")), (
                "a non-dispatch CI job sets the live-lanes env; required tier must stay hermetic"
            )


def test_docs_consistency_is_a_separate_named_check() -> None:
    """The ontology / status / public-surface check is its own job, separate from unit tests."""
    docs = [job for job in _jobs().values() if "ontology or public_surface" in _run_text(job)]
    assert len(docs) == 1
    assert "not live_lane" not in _run_text(docs[0])  # it is not the unit-test job


def test_live_connectors_remain_opt_in_after_coverage() -> None:
    """Even after EG-R4 flips EG-M5C-6 to ``covered``, the three connector lanes remain opt-in: each
    is conservatively mature (never ``now``) and pins its own optional SDK extra, so being covered
    never promotes a provider SDK into the required runtime."""
    registry = built_in_lanes()
    for name in ("langfuse-trace", "phoenix-trace", "langsmith-trace"):
        lane = registry.get(name)
        assert lane.maturity is not Maturity.NOW, f"{name} must never be a 'now' default"
        assert lane.optional_dependencies, f"{name} must pin its own opt-in SDK extra"
