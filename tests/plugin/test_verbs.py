"""EGP-P1-2..10: the umbrella's verb routing names the correct, honest execution targets.

The verbs are skill-routed (the agent issues the Bash); these assertions pin the load-bearing
invariants of that routing so a refactor can't silently break the runtime boundary or the
no-false-confidence posture. Whitespace is normalized so wrapping is not brittle.
"""

from __future__ import annotations

from tests.plugin.conftest import REPO_ROOT

_UMBRELLA = REPO_ROOT / "skills" / "evalglass" / "SKILL.md"


def _normalized() -> str:
    return " ".join(_UMBRELLA.read_text(encoding="utf-8").lower().split())


def test_host_run_uses_vendored_runtime_not_framework() -> None:
    text = _normalized()
    # Host evaluation goes through the vendored namespace with PYTHONPATH=evals …
    assert "pythonpath=evals python -m _evalglass.harness.cli run" in text
    # … and never the framework package for a host run.
    assert "pythonpath=evals python -m evalglass.harness" not in text


def test_setup_uses_the_bundled_launcher() -> None:
    assert "evalglass-launch" in _normalized()


def test_connect_v1_is_hermetic_import_and_live_is_opt_in_v1_1() -> None:
    text = _normalized()
    assert "openinference" in text  # exported OTel/OpenInference import is the v1 source
    assert "proposed" in text  # scaffolded data stays proposed
    assert "connect --live" in text  # live platform pull exists as a lane…
    assert "v1.1" in text  # …but only as the opt-in v1.1 lane, never a v1 default
    assert "no provider sdk" in text  # and EvalGlass ships no provider SDK


def test_view_by_call_is_enabled_and_groups_by_subject_identity() -> None:
    """F1 landed (the artifact-shape gate is green) → by-call ships, grouping by explicit
    Score subject identity (example_id/unit_id), never by list order."""
    text = _normalized()
    assert "--by-call" in text
    assert "example_id" in text
    assert "unit_id" in text
    # the old "blocked until F1" framing must be gone
    assert "waits on framework slice" not in text
    # per-source-function attribution stays an advanced extension, not this view
    assert "source-function" in text or "source function" in text


def test_quickstart_uses_bundled_example() -> None:
    text = _normalized()
    assert "run --example quickstart" in text
    assert "examples/quickstart/evals/evalglass.yaml" in text


def test_ci_is_scaffold_copy_with_no_plugin_reference() -> None:
    text = _normalized()
    assert "evals/ci/github-actions.yml" in text
    # The CI verb description must say the wired workflow references neither plugin nor launcher.
    assert "references neither the plugin nor the launcher" in text


def test_view_never_zero_for_blocked() -> None:
    assert "never `0.0`" in _UMBRELLA.read_text(encoding="utf-8")
