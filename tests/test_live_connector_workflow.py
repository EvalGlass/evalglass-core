"""Secret-gated live-connector workflow (EG-R0-6; ADR 0033).

A maintainer can exercise the real Langfuse / Phoenix / LangSmith connectors through the manual
``live-lanes`` job, but live access never becomes a required gate and provider secrets never reach
the required tier. This guard pins that contract on ``.github/workflows/ci.yml``:

- the live-lanes job wires each provider's credential env vars (from optional GitHub secrets) so a
  dispatched run can do a real pull; absent secrets simply skip;
- any job referencing a provider secret is manual ``workflow_dispatch`` only;
- after the live tier, the job re-runs the hermetic guards (dependency budget + import boundary) so
  a live run that somehow perturbed deps/imports is caught (post-live rearm);
- the required tier still runs ``-m "not live_lane"`` (the hermetic invariant, also locked by
  ``tests/test_hermetic_tranche_lock.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
_PROVIDERS = ("langfuse", "phoenix", "langsmith")


def _jobs() -> dict[str, Any]:
    return dict(yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"])


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(str(s.get("run", "")) for s in job.get("steps", []) if isinstance(s, dict))


def _live_job() -> dict[str, Any]:
    live: list[dict[str, Any]] = [
        job for job in _jobs().values() if "-m live_lane" in _run_text(job)
    ]
    assert len(live) == 1, "exactly one manual live-lanes job is expected"
    return live[0]


def test_live_job_wires_each_provider_credential() -> None:
    dump = yaml.safe_dump(_live_job()).lower()
    for provider in _PROVIDERS:
        assert provider in dump, (
            f"the live-lanes job wires no {provider} credentials for a real pull"
        )


def test_provider_secrets_only_in_manual_dispatch_jobs() -> None:
    for name, job in _jobs().items():
        dump = yaml.safe_dump(job).lower()
        if any(f"secrets.{provider}" in dump for provider in _PROVIDERS):
            assert "workflow_dispatch" in str(job.get("if", "")), (
                f"job {name!r} exposes provider secrets outside a manual-dispatch job"
            )


def test_live_job_wires_each_connector_real_pull_skip_guard() -> None:
    """Each connector's live test runs only when its ``EVALGLASS_<VENDOR>_ENDPOINT`` is set; the
    job must wire all three, or a secret-configured dispatch would silently skip every connector
    and go green without exercising one."""
    dump = yaml.safe_dump(_live_job())
    for provider in _PROVIDERS:
        guard = f"EVALGLASS_{provider.upper()}_ENDPOINT"
        assert guard in dump, f"the live-lanes job does not wire the {guard} real-pull skip-guard"


def test_post_live_guard_rearm_step_exists() -> None:
    text = _run_text(_live_job())
    assert "test_dependency_budget" in text, "live job must re-run the dependency-budget guard"
    assert "test_connector_import_boundary" in text, (
        "live job must re-run the import-boundary guard after the live tier (post-live rearm)"
    )


def test_required_tier_still_excludes_live_lane() -> None:
    assert any("not live_lane" in _run_text(job) for job in _jobs().values())
