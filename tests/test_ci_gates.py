"""EG-AT0-2 — CI gate guards.

Proves the intended CI tiers are wired and, crucially, that **no required
alignment gate lives only under ``.claude/``** (GitHub CI excludes that tree, so
a gate hidden there would never run — CLAUDE.md §21 Lesson 4). The required
``tests`` job runs hermetically (``-m "not live_lane"``); a named
``docs-consistency`` check runs the ontology/status/public-surface markers over
``tests/``; and ``live-lanes`` is opt-in (manual dispatch, never required).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

_CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict[str, object]:
    data = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _job_text(job: object) -> str:
    """Flatten a job's ``run`` steps into one searchable string."""
    steps = job.get("steps", []) if isinstance(job, dict) else []
    return "\n".join(str(s.get("run", "")) for s in steps if isinstance(s, dict))


@pytest.fixture
def jobs() -> dict[str, object]:
    workflow = _workflow()
    assert isinstance(workflow, dict)
    found = workflow["jobs"]
    assert isinstance(found, dict)
    return found


def test_required_tests_job_is_hermetic(jobs: dict[str, object]) -> None:
    assert "not live_lane" in _job_text(jobs["tests"])


def test_docs_consistency_named_check_runs_alignment_markers(jobs: dict[str, object]) -> None:
    text = _job_text(jobs["docs-consistency"])
    assert "ontology or public_surface" in text
    # It must NOT route through the .claude tree — alignment gates run under tests/.
    assert ".claude" not in text


def test_live_lanes_job_is_opt_in_and_not_required(jobs: dict[str, object]) -> None:
    live = jobs["live-lanes"]
    assert isinstance(live, dict)
    assert live.get("if") == "github.event_name == 'workflow_dispatch'"
    assert "live_lane" in _job_text(live)
    needs = jobs["all-checks-passed"]
    assert isinstance(needs, dict)
    required = needs.get("needs", [])
    assert "live-lanes" not in required  # never a required gate
    assert "docs-consistency" in required  # but docs-consistency is


def _aggregator_step(jobs: dict[str, object]) -> dict[str, object]:
    agg = jobs["all-checks-passed"]
    assert isinstance(agg, dict)
    step = next(s for s in agg["steps"] if isinstance(s, dict) and "env" in s and "run" in s)
    assert isinstance(step, dict)
    return step


def _fail_logic(step: dict[str, object]) -> str:
    """The aggregator's run script *minus* status ``echo`` lines — a var merely logged but
    omitted from the fail loop must not count as enforced."""
    return "\n".join(
        line for line in str(step["run"]).splitlines() if not line.strip().startswith("echo")
    )


def test_aggregator_enforces_every_required_job(jobs: dict[str, object]) -> None:
    """Each job the aggregator ``needs`` must have its ``.result`` both bound to an env var AND
    referenced in the fail logic — otherwise a failing required job (e.g. ``docs-consistency``)
    would still yield a green 'all required checks'. This is the no-false-confidence doctrine
    applied to our own CI (CLAUDE.md §21 Lesson 1)."""
    agg = jobs["all-checks-passed"]
    assert isinstance(agg, dict)
    required = agg.get("needs", [])
    assert isinstance(required, list)
    step = _aggregator_step(jobs)
    env = step["env"]
    assert isinstance(env, dict)
    fail_logic = _fail_logic(step)  # the for-loop + conditionals, NOT the status echo
    for job in required:
        bound = [name for name, value in env.items() if f"needs.{job}.result" in str(value)]
        assert bound, f"aggregator does not read needs.{job}.result"
        assert any(name in fail_logic for name in bound), (
            f"aggregator reads needs.{job}.result but never enforces it in the fail logic"
        )


def test_docs_consistency_result_is_enforced_by_the_aggregator(jobs: dict[str, object]) -> None:
    """Regression guard for the specific gap: docs-consistency must be enforced, not just listed."""
    step = _aggregator_step(jobs)
    env = step["env"]
    assert isinstance(env, dict)
    docs_vars = [n for n, v in env.items() if "needs.docs-consistency.result" in str(v)]
    assert docs_vars, "docs-consistency result is not bound in the aggregator"
    assert any(name in _fail_logic(step) for name in docs_vars), (
        "docs-consistency result is read but never checked in the fail loop"
    )


def test_no_alignment_gate_lives_only_under_dot_claude(jobs: dict[str, object]) -> None:
    """The jobs that execute alignment tests must run under ``tests/``, never ``.claude/``.

    (The ``typecheck`` and ``skill-tests`` jobs legitimately touch ``.claude/`` to
    lint/run the scan-gate & validator-gate *skills* — those are not alignment
    gates.) The required ``tests`` and ``docs-consistency`` jobs run the alignment
    markers/suites and must therefore never scope pytest to ``.claude``.
    """
    for name in ("tests", "docs-consistency"):
        assert ".claude" not in _job_text(jobs[name]), (
            f"alignment job {name!r} must run under tests/, never scope pytest to .claude"
        )
