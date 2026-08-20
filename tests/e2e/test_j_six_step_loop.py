"""Six-step loop journey — Ask/Observe/Shape/Run/Read/Improve (EG-AT6-3; alignment plan §F 8.2).

The product is presented as an everyday loop. This journey proves the loop maps to real artifacts
(Run produces a typed Scorecard/RunRecord that Read consumes), that per-call subject identity is
stamped where the runner can, that a delta is only claimed when the baseline is comparable, and that
the loop's documented prose does not overclaim (the *tool* never certifies quality).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

import evalglass
from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost

pytestmark = pytest.mark.fixture_e2e

_ARCH_HTML = (
    Path(evalglass.__file__).resolve().parents[2]
    / "docs"
    / "evalglass-product-architecture-current.html"
)
_LOOP_STEPS = ("Ask", "Observe", "Shape", "Run", "Read", "Improve")


def _loop_section() -> str:
    html = _ARCH_HTML.read_text(encoding="utf-8")
    match = re.search(r'id="loop".*?</section>', html, re.DOTALL)
    assert match is not None, "the architecture map has no #loop section"
    return match.group(0)


def test_run_and_read_produce_typed_artifacts(
    installed_host: VendoredHost, vendored_run: Callable[..., CliResult]
) -> None:
    """Run -> typed Scorecard + RunRecord; Read consumes their fields (not recomputation)."""
    result = vendored_run(installed_host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    assert result.scorecard is not None
    assert result.runrecord is not None
    # Read surfaces the same verdict the RunRecord embeds — rendered, never recomputed.
    assert result.runrecord["scorecard"]["verdict"] == result.scorecard["verdict"]


def test_by_call_identity_is_stamped_on_scores(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    """--by-call identity: every score carries explicit example_id/unit_id where stamped."""
    host = make_host(AuthorityState.COMPARABLE_BASELINE)
    result = vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0  # the run under test succeeded (not a stale prep artifact)
    assert result.runrecord is not None
    scores = result.runrecord["scores"]
    assert scores
    for score in scores:
        assert score["example_id"], "a score is missing its example_id (by-call identity)"
        assert score["unit_id"], "a score is missing its unit_id"


def test_delta_only_renders_when_baseline_is_comparable(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    """A regression delta is claimed only when provenance says the runs are comparable."""
    comparable = vendored_run(
        make_host(AuthorityState.COMPARABLE_BASELINE), "run", "--config", "evals/evalglass.yaml"
    )
    not_comparable = vendored_run(
        make_host(AuthorityState.NOT_COMPARABLE_BASELINE), "run", "--config", "evals/evalglass.yaml"
    )
    assert comparable.exit_code == 0
    assert not_comparable.exit_code == 0
    assert comparable.scorecard is not None
    assert not_comparable.scorecard is not None
    assert comparable.scorecard["baseline_state"] == "comparable"
    assert not_comparable.scorecard["baseline_state"] == "not_comparable"
    # A non-comparable run prints no regression delta on any surface.
    for surface in (not_comparable.stdout.lower(), (not_comparable.report or "").lower()):
        assert "regression" not in surface


def test_six_step_loop_is_documented_without_tool_overclaim() -> None:
    """Each loop step is documented, and the loop prose never has the tool certify quality.

    ``approve``/``safe`` are intentionally not banned here — the docs legitimately speak of a
    *host-approved* gate and *security*; the unambiguous unearned-success terms must be absent.
    """
    section = _loop_section()
    for step in _LOOP_STEPS:
        assert f">{step}<" in section, f"the six-step loop is missing the {step!r} step"
    lowered = section.lower()
    for word in ("certify", "certified", "production-ready", "proof of correctness", "guaranteed"):
        assert word not in lowered, f"the loop prose overclaims: {word!r}"
