"""J8/J9 baseline, J10 CI, J6 view, J7 explain, J16/J19 removal (EG-AT6-7; plan §F 8.8-8.15).

The high-use workflows read typed outputs and never recompute meaning: a delta renders only when
comparable, an ordinary run promotes no baseline, the CI exit derives only from ``ci_should_fail``,
a rendered annotation cites only reasons present in the Scorecard, non-scored examples carry no
value, and removing the plugin leaves the verdict byte-identical.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost

pytestmark = pytest.mark.fixture_e2e


def _run(host: VendoredHost, *args: str, plugin_present: bool = False) -> CliResult:
    result = host.run(
        ["run", "--config", "evals/evalglass.yaml", *args], plugin_present=plugin_present
    )
    assert result.exit_code in (0, 1), f"unexpected infra exit {result.exit_code}: {result.stderr}"
    return result


# --- J8/J9 baseline ---------------------------------------------------------
def test_j8_delta_renders_only_when_baseline_is_comparable(
    make_host: Callable[..., VendoredHost],
) -> None:
    comparable = _run(make_host(AuthorityState.COMPARABLE_BASELINE))
    not_comparable = _run(make_host(AuthorityState.NOT_COMPARABLE_BASELINE))
    assert comparable.scorecard is not None
    assert not_comparable.scorecard is not None
    assert comparable.scorecard["baseline_state"] == "comparable"
    assert not_comparable.scorecard["baseline_state"] == "not_comparable"
    for surface in (not_comparable.stdout.lower(), (not_comparable.report or "").lower()):
        assert "regression" not in surface


def test_j9_an_ordinary_run_promotes_no_baseline(
    make_host: Callable[..., VendoredHost],
) -> None:
    host = make_host(AuthorityState.HOST_PROMOTED_GATE)
    baselines = host.evals_dir / "baselines"
    before = sorted(p.name for p in baselines.glob("*")) if baselines.exists() else []
    _run(host)
    after = sorted(p.name for p in baselines.glob("*")) if baselines.exists() else []
    assert after == before, "an ordinary run wrote a baseline (promotion must be explicit)"


# --- J10 CI -----------------------------------------------------------------
def test_j10_ci_exit_derives_only_from_ci_should_fail(
    make_host: Callable[..., VendoredHost],
) -> None:
    result = _run(make_host(AuthorityState.HOST_PROMOTED_GATE), "--format", "ci")
    assert result.scorecard is not None
    ci_should_fail = result.scorecard["verdict"]["ci_should_fail"]
    first = result.stdout.splitlines()[0]
    assert first.startswith("::notice title=EvalGlass::verdict=")
    expected = "exit-zero" if ci_should_fail is False else "exit-nonzero"
    assert f"ci={expected}" in first
    assert result.exit_code == (0 if ci_should_fail is False else 1)


def test_j7_ci_annotation_reasons_are_a_subset_of_scorecard_reasons(
    make_host: Callable[..., VendoredHost],
) -> None:
    """A rendered annotation cites only reasons present in the typed Scorecard (no overclaim)."""
    result = _run(make_host(AuthorityState.UNCALIBRATED_JUDGE), "--format", "ci")
    assert result.scorecard is not None
    present = {
        r for authority in result.scorecard["authority"].values() for r in authority["reasons"]
    }
    for line in result.stdout.splitlines():
        if "authority=" in line:
            rendered = line.split("authority=", 1)[1].strip()
            if rendered in ("none", ""):
                continue
            for token in (t.strip() for t in rendered.split(",")):
                assert token in present, (
                    f"annotation cites a reason absent from the Scorecard: {token!r}"
                )


# --- J6 view ----------------------------------------------------------------
def test_j6_view_non_scored_example_has_no_value(
    make_host: Callable[..., VendoredHost],
) -> None:
    result = _run(make_host(AuthorityState.WORST_SOURCE_DILUTED))
    assert result.runrecord is not None
    non_scored = [s for s in result.runrecord["scores"] if s["status"] != "scored"]
    assert non_scored, "expected a non-scored example in the worst-source state"
    for score in non_scored:
        assert score["value"] is None
        assert score["example_id"]  # by-call identity still stamped
        assert score["unit_id"]


# --- J16/J19 removal --------------------------------------------------------
def test_j16_removal_leaves_the_verdict_byte_identical(
    make_host: Callable[..., VendoredHost],
) -> None:
    host = make_host(AuthorityState.HOST_PROMOTED_GATE)
    without_plugin = _run(host, plugin_present=False)
    with_plugin = _run(host, plugin_present=True)
    assert without_plugin.scorecard is not None
    assert with_plugin.scorecard is not None
    assert json.dumps(without_plugin.scorecard["verdict"], sort_keys=True) == json.dumps(
        with_plugin.scorecard["verdict"], sort_keys=True
    )
